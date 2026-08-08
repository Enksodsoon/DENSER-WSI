from __future__ import annotations

from pathlib import Path

import pytest

from denser.core.errors import PartitionViolation
from denser.data.manifest import PartitionManifest, SlideRecord
from denser.evidence.controls import ControlPair
from denser.experiments.development import DevelopmentConfig, run_development


def manifest(partition: str) -> PartitionManifest:
    row = SlideRecord("synthetic-r1", "SYNTHETIC", "a" * 64, "b" * 64, 100, partition, None)
    return PartitionManifest("MC-V1-manifest-1", 1, (row,), "c" * 64)


def test_development_refuses_non_development_slide(tmp_path: Path) -> None:
    with pytest.raises(PartitionViolation):
        run_development(DevelopmentConfig(tmp_path), manifest("pilot"))


def test_development_without_bound_source_pixels_is_access_limited(tmp_path: Path) -> None:
    report = run_development(DevelopmentConfig(tmp_path), manifest("development"))
    assert report.status == "external_access_limited"
    assert report.calibration_digest is None
    assert report.candidate_steps == (1.0, 2.0, 4.0)


def _pair(control_id: str, tile_id: str, kind: str, value: float) -> ControlPair:
    groups = (
        ("nuclear_objects", (value,)),
        ("architecture", (value,)),
        ("rare_event_sentinels", (value,)),
        ("visual", (value,)),
    )
    expected = "nuclear_objects" if kind == "harmful" else None
    return ControlPair(control_id, tile_id, kind, expected, groups)


def test_development_requires_harmful_control_detection_before_completion(tmp_path: Path) -> None:
    controls = (
        _pair("benign-1", "tile-1", "benign", 0.01),
        _pair("benign-2", "tile-2", "benign", 0.02),
        _pair("harmful-1", "tile-3", "harmful", 0.01),
    )
    report = run_development(
        DevelopmentConfig(tmp_path, control_pairs=controls), manifest("development")
    )
    assert report.status == "control_audit_failed"
    assert report.calibration_digest is None
    assert report.calibration_audit_status == "not_evaluable"


def test_development_completes_only_after_harmful_control_audit_passes(tmp_path: Path) -> None:
    controls = (
        _pair("benign-1", "tile-1", "benign", 0.01),
        _pair("benign-2", "tile-2", "benign", 0.02),
        _pair("harmful-1", "tile-3", "harmful", 9.0),
    )
    report = run_development(
        DevelopmentConfig(tmp_path, control_pairs=controls), manifest("development")
    )
    assert report.status == "complete"
    assert report.calibration_digest is not None
    assert report.calibration_audit_status == "calibrated"
