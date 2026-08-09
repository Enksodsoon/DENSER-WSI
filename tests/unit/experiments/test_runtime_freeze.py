from __future__ import annotations

from pathlib import Path

import json
import pytest

from denser.experiments.runtime_freeze import (
    require_bound_phase_evidence,
    runtime_freeze_paths,
)


def test_runtime_freeze_binds_execution_and_analysis_entrypoints() -> None:
    root = Path(__file__).parents[3]
    paths = {path.relative_to(root).as_posix() for path in runtime_freeze_paths(root)}
    assert "scripts/create_private_freeze.py" in paths
    assert "scripts/run_private_final.py" in paths
    assert "scripts/analyze_private_final.py" in paths
    assert "src/denser/analysis/final_results.py" in paths
    assert "src/denser/experiments/robustness.py" in paths


def test_freeze_phase_evidence_must_match_route_calibration_and_gate(
    tmp_path: Path,
) -> None:
    report = {
        "source_data_processed": True,
        "phase_classification": "evaluable",
        "standard_routing_digest": "route",
        "calibration_digest": "calibration",
        "candidate_workers": 1,
        "generation_gate": {"passed": False},
    }
    path = tmp_path / "feasibility-development.private.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="passing development gate"):
        require_bound_phase_evidence(
            tmp_path,
            "development",
            routing_digest="route",
            calibration_digest="calibration",
        )
    report["generation_gate"]["passed"] = True
    path.write_text(json.dumps(report), encoding="utf-8")
    selected = require_bound_phase_evidence(
        tmp_path,
        "development",
        routing_digest="route",
        calibration_digest="calibration",
    )
    assert selected == report

    report["standard_routing_digest"] = "stale"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="bound development evidence"):
        require_bound_phase_evidence(
            tmp_path,
            "development",
            routing_digest="route",
            calibration_digest="calibration",
        )
