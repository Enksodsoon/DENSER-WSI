from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
from pathlib import Path

from denser.data.models import DownloadRecord, GdcSlideRecord


class DownloadIntegrityError(RuntimeError):
    """Downloaded bytes failed an immutable source check."""


def _quarantine_path(destination: Path) -> Path:
    run_root = destination.parent.parent
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
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                md5.update(block)
                sha256.update(block)
                byte_count += len(block)
            output.flush()
            os.fsync(output.fileno())
        if md5.hexdigest().lower() != record.md5.lower():
            shutil.move(str(temporary), str(_quarantine_path(destination)))
            raise DownloadIntegrityError("downloaded MD5 does not match GDC record")
        if byte_count != record.file_size:
            shutil.move(str(temporary), str(_quarantine_path(destination)))
            raise DownloadIntegrityError("downloaded size does not match GDC record")
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise
    return DownloadRecord(
        research_id=record.research_id,
        destination=str(destination.resolve()),
        byte_count=byte_count,
        source_md5=md5.hexdigest(),
        sha256=sha256.hexdigest(),
        verified=True,
    )
