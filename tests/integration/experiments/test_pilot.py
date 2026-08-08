from __future__ import annotations

from pathlib import Path

import pytest

from denser.core.errors import PartitionViolation
from denser.data.manifest import PartitionManifest, SlideRecord
from denser.experiments.pilot import PilotConfig, PilotObservation, run_pilot


def manifest(partition: str = "pilot") -> PartitionManifest:
    row = SlideRecord("synthetic-p1", "SYNTHETIC", "a" * 64, "b" * 64, 100, partition, None)
    return PartitionManifest("MC-V1-manifest-1", 1, (row,), "c" * 64)


def test_pilot_report_is_sampled_scope_only(tmp_path: Path) -> None:
    report = run_pilot(PilotConfig(tmp_path), manifest(), calibration_digest="d" * 64)
    assert report.rate_scope == "sampled_tiles_only"
    assert report.whole_slide_reduction is None
    assert report.classification == "not_evaluable"


def test_pilot_records_mechanism_metrics_without_extrapolation(tmp_path: Path) -> None:
    rows = (
        PilotObservation("standard", 1000, 0.0, 0.0, None),
        PilotObservation("uniform", 800, 0.0, 0.1, None),
        PilotObservation("denser", 700, 0.05, 0.0, 0.4),
    )
    report = run_pilot(PilotConfig(tmp_path, observations=rows), manifest(), "d" * 64)
    assert report.classification in {"met", "not_met"}
    assert report.complete_sampled_bytes == {"standard": 1000, "uniform": 800, "denser": 700}
    assert report.dns_median == 0.4


def test_pilot_rejects_wrong_partition(tmp_path: Path) -> None:
    with pytest.raises(PartitionViolation):
        run_pilot(PilotConfig(tmp_path), manifest("tuning"), "d" * 64)
