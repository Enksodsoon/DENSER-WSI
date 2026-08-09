from __future__ import annotations

import hashlib
import os
import re
import shutil
import urllib.request
from pathlib import Path

from denser.data.models import DownloadRecord, GdcSlideRecord


class DownloadIntegrityError(RuntimeError):
    """Downloaded bytes failed an immutable source check."""


_RANGE_BYTES = 64 * 1024 * 1024
_HTTP_TIMEOUT_SECONDS = 30


def _quarantine_path(destination: Path) -> Path:
    sources_root = next(
        (parent for parent in destination.parents if parent.name.casefold() == "sources"),
        destination.parent,
    )
    run_root = sources_root.parent
    quarantine = run_root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    return quarantine / f"{destination.name}.part"


def download_verified(record: GdcSlideRecord, destination: Path) -> DownloadRecord:
    if record.access != "open":
        raise ValueError("only open-access GDC files may be downloaded")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    url = record.content_url or f"https://api.gdc.cancer.gov/data/{record.file_uuid}"
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    byte_count = 0
    try:
        if temporary.exists():
            with temporary.open("rb") as partial:
                while block := partial.read(1024 * 1024):
                    md5.update(block)
                    sha256.update(block)
                    byte_count += len(block)
            if byte_count > record.file_size:
                temporary.unlink()
                md5 = hashlib.md5(usedforsecurity=False)
                sha256 = hashlib.sha256()
                byte_count = 0
        while byte_count < record.file_size:
            start = byte_count
            end = min(record.file_size - 1, start + _RANGE_BYTES - 1)
            headers = {
                "User-Agent": "DENSER-WSI/0.4 (+public-research)",
                "Range": f"bytes={start}-{end}",
            }
            request = urllib.request.Request(url, headers=headers)
            response = urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS)
            status = getattr(response, "status", None)
            if status == 206:
                expected_response_bytes = end - start + 1
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"(?:bytes )?(\d+)-(\d+)/(\d+)", content_range)
                if (
                    match is None
                    or int(match.group(1)) != start
                    or int(match.group(2)) < start
                    or int(match.group(3)) != record.file_size
                ):
                    response.close()
                    raise DownloadIntegrityError("server byte-range identity is invalid")
            elif status == 200 and start == 0:
                expected_response_bytes = record.file_size
            else:
                response.close()
                raise DownloadIntegrityError("server did not honor resumable byte range")
            received = 0
            with response, temporary.open("ab" if start else "wb") as output:
                while received < expected_response_bytes:
                    block = response.read(min(1024 * 1024, expected_response_bytes - received))
                    if not block:
                        break
                    output.write(block)
                    md5.update(block)
                    sha256.update(block)
                    byte_count += len(block)
                    received += len(block)
                output.flush()
                os.fsync(output.fileno())
            if received != expected_response_bytes:
                raise DownloadIntegrityError("byte-range response was truncated")
            if status == 200:
                break
        if md5.hexdigest().lower() != record.md5.lower():
            shutil.move(str(temporary), str(_quarantine_path(destination)))
            raise DownloadIntegrityError("downloaded MD5 does not match GDC record")
        if byte_count != record.file_size:
            shutil.move(str(temporary), str(_quarantine_path(destination)))
            raise DownloadIntegrityError("downloaded size does not match GDC record")
        os.replace(temporary, destination)
    except Exception:
        # Keep incomplete bytes for a verified HTTP Range resume. Integrity
        # mismatches above have already moved the partial into quarantine.
        raise
    return DownloadRecord(
        research_id=record.research_id,
        destination=str(destination.resolve()),
        byte_count=byte_count,
        source_md5=md5.hexdigest(),
        sha256=sha256.hexdigest(),
        verified=True,
    )
