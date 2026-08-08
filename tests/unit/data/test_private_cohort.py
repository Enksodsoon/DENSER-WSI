from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

import pytest

from denser.data.models import DownloadRecord
from denser.data.private_cohort import (
    bind_verified_partition_sources,
    download_manifest_partition,
)
from denser.governance.run_layout import RunLayout


def test_partition_downloader_is_sequential_resumable_and_private(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    run = tmp_path / "run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    layout.ensure()
    payload = b"slide"
    digest = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    rows = [
        {
            "access": "open",
            "case_id": f"case-{index}",
            "file_name": f"slide-{index}.svs",
            "file_size": len(payload),
            "file_uuid": f"file-{index}",
            "md5": digest,
            "partition": "development" if index < 2 else "final",
            "project_id": "TCGA-LUAD",
            "research_id": f"RS-{index}",
            "source_url": f"https://example.invalid/{index}",
        }
        for index in range(3)
    ]
    manifest = layout.resolve("manifests", "selected.private.json")
    manifest.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    calls: list[str] = []

    def fake_download(record, destination):  # type: ignore[no-untyped-def]
        calls.append(record.research_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return DownloadRecord(
            record.research_id,
            str(destination),
            len(payload),
            digest,
            hashlib.sha256(payload).hexdigest(),
            True,
        )

    first = download_manifest_partition(
        manifest, layout, "development", download_fn=fake_download
    )
    second = download_manifest_partition(
        manifest, layout, "development", download_fn=fake_download
    )
    assert len(first) == len(second) == 2
    assert calls == ["RS-0", "RS-1"]
    assert all(Path(row.destination).is_relative_to(run) for row in first)
    assert layout.resolve("checkpoints", "download-ledger.private.json").exists()


def test_partition_downloader_retries_transient_failure_without_advancing(tmp_path: Path) -> None:
    repo, run = tmp_path / "repo", tmp_path / "run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    layout.ensure()
    payload = b"slide"
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    row = {
        "access": "open", "case_id": "case", "file_name": "slide.svs",
        "file_size": len(payload), "file_uuid": "file", "md5": md5,
        "partition": "development", "project_id": "TCGA-LUAD",
        "research_id": "RS-retry", "source_url": "https://example.invalid",
    }
    manifest = layout.resolve("manifests", "selected.private.json")
    manifest.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    attempts = 0

    def flaky(record, destination):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("transient")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return DownloadRecord(record.research_id, str(destination), len(payload), md5, hashlib.sha256(payload).hexdigest(), True)

    result = download_manifest_partition(
        manifest, layout, "development", max_attempts_per_file=2, download_fn=flaky
    )
    assert len(result) == 1
    assert attempts == 2


def test_verified_partition_binding_uses_research_names_and_rejects_strays(tmp_path: Path) -> None:
    repo, run = tmp_path / "repo", tmp_path / "run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    layout.ensure()
    payload = b"slide"
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    rows = [
        {
            "access": "open", "case_id": f"case-{index}",
            "file_name": f"original-{index}.svs", "file_size": len(payload),
            "file_uuid": f"file-{index}", "md5": md5,
            "partition": "development", "project_id": f"TCGA-{index}",
            "research_id": f"RS-{index}", "source_url": "https://example.invalid",
        }
        for index in range(2)
    ]
    manifest = layout.resolve("manifests", "selected.private.json")
    manifest.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    source_root = layout.resolve("sources", "development")
    source_root.mkdir(parents=True)
    for index in range(2):
        (source_root / f"RS-{index}.svs").write_bytes(payload)
    bound = bind_verified_partition_sources(
        manifest, layout, "development", expected_count=2
    )
    assert [item.path.name for item in bound] == ["RS-0.svs", "RS-1.svs"]
    (source_root / "stray.svs").write_bytes(payload)
    with pytest.raises(RuntimeError, match="exactly match"):
        bind_verified_partition_sources(manifest, layout, "development", expected_count=2)


def test_verified_partition_binding_rejects_same_size_corruption(tmp_path: Path) -> None:
    repo, run = tmp_path / "repo", tmp_path / "run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    layout.ensure()
    payload = b"slide"
    row = {
        "access": "open", "case_id": "case", "file_name": "original.svs",
        "file_size": len(payload), "file_uuid": "file",
        "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        "partition": "development", "project_id": "TCGA-X",
        "research_id": "RS-corrupt", "source_url": "https://example.invalid",
    }
    manifest = layout.resolve("manifests", "selected.private.json")
    manifest.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    source = layout.resolve("sources", "development", "RS-corrupt.svs")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"wrong")
    with pytest.raises(RuntimeError, match="integrity"):
        bind_verified_partition_sources(manifest, layout, "development", expected_count=1)


def test_partition_downloader_bounds_distinct_file_concurrency(tmp_path: Path) -> None:
    repo, run = tmp_path / "repo", tmp_path / "run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    layout.ensure()
    payload = b"slide"
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    rows = [
        {
            "access": "open", "case_id": f"case-{index}",
            "file_name": f"slide-{index}.svs", "file_size": len(payload),
            "file_uuid": f"file-{index}", "md5": md5,
            "partition": "development", "project_id": f"TCGA-{index}",
            "research_id": f"RS-{index}", "source_url": "https://example.invalid",
        }
        for index in range(2)
    ]
    manifest = layout.resolve("manifests", "selected.private.json")
    manifest.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    barrier = threading.Barrier(2)
    active = 0
    peak = 0
    guard = threading.Lock()

    def concurrent_download(record, destination):  # type: ignore[no-untyped-def]
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        barrier.wait(timeout=5)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        with guard:
            active -= 1
        return DownloadRecord(
            record.research_id, str(destination), len(payload), md5,
            hashlib.sha256(payload).hexdigest(), True,
        )

    result = download_manifest_partition(
        manifest,
        layout,
        "development",
        max_concurrent_files=2,
        download_fn=concurrent_download,
    )
    assert len(result) == 2
    assert peak == 2
