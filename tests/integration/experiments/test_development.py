from __future__ import annotations

from pathlib import Path

import pytest

from denser.core.errors import PartitionViolation
from denser.data.manifest import PartitionManifest, SlideRecord
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
