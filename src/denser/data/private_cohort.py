from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.data.download import download_verified
from denser.data.models import DownloadRecord, GdcSlideRecord
from denser.governance.run_layout import RunLayout


DownloadFunction = Callable[[GdcSlideRecord, Path], DownloadRecord]
_SAFE_RESEARCH_ID = re.compile(r"^RS-[a-zA-Z0-9-]+$")


@dataclass(frozen=True, slots=True)
class VerifiedPrivateSource:
    record: GdcSlideRecord
    path: Path


def _source_parts(generation: int, partition: str) -> tuple[str, ...]:
    if generation <= 0:
        raise ValueError("generation must be positive")
    if generation == 1:
        return ("sources", partition)
    return ("sources", f"generation-{generation}", partition)


def _record(row: dict[str, object]) -> GdcSlideRecord:
    required = {
        "access",
        "case_id",
        "file_name",
        "file_size",
        "file_uuid",
        "md5",
        "project_id",
        "research_id",
        "source_url",
    }
    if not required.issubset(row):
        raise ValueError("private source manifest row is incomplete")
    research_id = str(row["research_id"])
    if not _SAFE_RESEARCH_ID.fullmatch(research_id):
        raise ValueError("private research identifier is not path-safe")
    return GdcSlideRecord(
        research_id=research_id,
        file_uuid=str(row["file_uuid"]),
        file_name=str(row["file_name"]),
        project_id=str(row["project_id"]),
        case_id=str(row["case_id"]),
        primary_site=None,
        stain_type="H&E",
        magnification=None,
        mpp=None,
        file_size=int(row["file_size"]),
        md5=str(row["md5"]),
        release="released",
        access=str(row["access"]),
        content_url=str(row["source_url"]),
    )


def _verify_existing(record: GdcSlideRecord, path: Path) -> DownloadRecord | None:
    if not path.is_file() or path.stat().st_size != record.file_size:
        return None
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            md5.update(block)
            sha256.update(block)
    if md5.hexdigest().lower() != record.md5.lower():
        return None
    return DownloadRecord(
        record.research_id,
        str(path.resolve()),
        record.file_size,
        md5.hexdigest(),
        sha256.hexdigest(),
        True,
    )


def _write_ledger(path: Path, rows: list[DownloadRecord]) -> None:
    document = {
        "version": "DENSER-private-download-ledger-1",
        "records": [asdict(row) for row in rows],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(document) + b"\n")
    temporary.replace(path)


def bind_verified_partition_sources(
    manifest_path: Path,
    layout: RunLayout,
    partition: str,
    *,
    expected_count: int,
    generation: int = 1,
) -> tuple[VerifiedPrivateSource, ...]:
    """Resolve an exact, integrity-checked private source set from its manifest."""
    if partition not in {"development", "pilot", "tuning", "final"}:
        raise ValueError("unknown cohort partition")
    if expected_count <= 0:
        raise ValueError("expected source count must be positive")
    manifest = Path(manifest_path).resolve(strict=True)
    if not manifest.is_relative_to(layout.resolve("manifests")):
        raise ValueError("private source manifest must remain beneath run manifests")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    raw_rows = document.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("private source manifest rows are invalid")
    selected = [row for row in raw_rows if isinstance(row, dict) and row.get("partition") == partition]
    selected.sort(key=lambda row: (str(row.get("project_id")), str(row.get("research_id"))))
    if len(selected) != expected_count:
        raise RuntimeError("private partition does not contain the exact expected source count")
    records = tuple(_record(row) for row in selected)
    if len({record.research_id for record in records}) != len(records):
        raise RuntimeError("private partition research identifiers are not unique")
    if len({record.case_id for record in records}) != len(records):
        raise RuntimeError("private partition cases are not disjoint")
    source_parts = _source_parts(generation, partition)
    source_root = layout.resolve(*source_parts)
    expected_paths = tuple(
        layout.resolve(*source_parts, f"{record.research_id}.svs")
        for record in records
    )
    observed_paths = set(source_root.glob("*.svs")) if source_root.exists() else set()
    if observed_paths != set(expected_paths):
        raise RuntimeError("private source files do not exactly match the bound manifest")
    bound = []
    for record, path in zip(records, expected_paths, strict=True):
        if record.access != "open" or _verify_existing(record, path) is None:
            raise RuntimeError("private source integrity verification failed")
        bound.append(VerifiedPrivateSource(record, path))
    return tuple(bound)


def download_manifest_partition(
    manifest_path: Path,
    layout: RunLayout,
    partition: str,
    *,
    max_files: int | None = None,
    max_attempts_per_file: int = 12,
    max_concurrent_files: int = 1,
    generation: int = 1,
    download_fn: DownloadFunction = download_verified,
) -> tuple[DownloadRecord, ...]:
    if partition not in {"development", "pilot", "tuning", "final"}:
        raise ValueError("unknown cohort partition")
    if max_attempts_per_file <= 0:
        raise ValueError("max_attempts_per_file must be positive")
    if max_concurrent_files not in (1, 2):
        raise ValueError("private download concurrency must be one or two files")
    layout.ensure()
    manifest = Path(manifest_path).resolve(strict=True)
    if not manifest.is_relative_to(layout.resolve("manifests")):
        raise ValueError("private source manifest must remain beneath run manifests")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    raw_rows = document.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("private source manifest rows are invalid")
    selected = [row for row in raw_rows if isinstance(row, dict) and row.get("partition") == partition]
    selected.sort(key=lambda row: (str(row.get("project_id")), str(row.get("research_id"))))
    if max_files is not None:
        if max_files <= 0:
            raise ValueError("max_files must be positive")
        selected = selected[:max_files]
    records = tuple(_record(row) for row in selected)
    source_parts = _source_parts(generation, partition)

    def acquire(record: GdcSlideRecord) -> DownloadRecord:
        if record.access != "open":
            raise ValueError("only open-access cohort records may be downloaded")
        destination = layout.resolve(*source_parts, f"{record.research_id}.svs")
        destination.parent.mkdir(parents=True, exist_ok=True)
        existing = _verify_existing(record, destination)
        if existing is None:
            if destination.exists():
                quarantine = layout.resolve(
                    "quarantine", f"generation-{generation}-{record.research_id}.invalid"
                )
                destination.replace(quarantine)
            last_error: OSError | RuntimeError | None = None
            for _attempt in range(max_attempts_per_file):
                try:
                    existing = download_fn(record, destination)
                    break
                except (OSError, RuntimeError) as error:
                    last_error = error
            else:
                raise RuntimeError("verified private download exhausted bounded retries") from last_error
        return existing

    completed: dict[str, DownloadRecord] = {}
    with ThreadPoolExecutor(max_workers=max_concurrent_files) as pool:
        futures = {pool.submit(acquire, record): record.research_id for record in records}
        for future in as_completed(futures):
            result = future.result()
            completed[result.research_id] = result
            _write_ledger(
                layout.resolve(
                    "checkpoints",
                    "download-ledger.private.json"
                    if generation == 1
                    else f"download-ledger-generation-{generation}.private.json",
                ),
                [completed[key] for key in sorted(completed)],
            )
    return tuple(completed[record.research_id] for record in records)
