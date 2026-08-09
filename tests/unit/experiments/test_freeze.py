from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from denser.core.errors import FreezeViolation
from denser.experiments.freeze import (
    FreezeContext,
    create_freeze_record,
    freeze_record_from_dict,
    verify_freeze_record,
    write_freeze_record,
)


def context(**changes: object) -> FreezeContext:
    base = FreezeContext(
        git_commit="a" * 40,
        dirty_tree=False,
        container_image_digest="sha256:" + "b" * 64,
        sbom_digest="c" * 64,
        dependency_versions=(("python", "3.12.13"),),
        configuration_digest="d" * 64,
        partition_manifest_digest="e" * 64,
        reserve_manifest_digest="f" * 64,
        selected_profile_id="DENSER-P3",
        profile_digest="1" * 64,
        standard_candidate_ladders=(("jpeg", (70.0, 80.0, 90.0)),),
        evidence_tolerances=(("visual", 0.2),),
        evidence_implementation_digest="2" * 64,
        analysis_code_digest="3" * 64,
        random_seeds=(20260807, 9),
        expected_final_slide_count=18,
    )
    return replace(base, **changes)


def test_freeze_fails_on_dirty_tree() -> None:
    with pytest.raises(FreezeViolation):
        create_freeze_record(context(dirty_tree=True))


def test_final_runner_rejects_changed_profile_digest() -> None:
    record = create_freeze_record(context())
    with pytest.raises(FreezeViolation):
        verify_freeze_record(record, context(profile_digest="0" * 64))


def test_freeze_is_written_atomically_with_digest_sidecar(tmp_path: Path) -> None:
    record = create_freeze_record(context())
    path = tmp_path / "freeze-record.json"
    write_freeze_record(path, record)
    assert path.exists()
    assert path.with_name("freeze-record.json.sha256").read_text().strip() == hashlib.sha256(path.read_bytes()).hexdigest()
    verify_freeze_record(record, context())


def test_freeze_record_mapping_round_trip_is_intrinsically_verified() -> None:
    record = create_freeze_record(context())
    assert freeze_record_from_dict(asdict(record)) == record
    tampered = asdict(record)
    tampered["selected_profile_id"] = "changed"
    with pytest.raises(FreezeViolation, match="digest"):
        freeze_record_from_dict(tampered)
