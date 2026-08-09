from __future__ import annotations

from pathlib import Path

from denser.experiments.runtime_freeze import runtime_freeze_paths


def test_runtime_freeze_binds_execution_and_analysis_entrypoints() -> None:
    root = Path(__file__).parents[3]
    paths = {path.relative_to(root).as_posix() for path in runtime_freeze_paths(root)}
    assert "scripts/create_private_freeze.py" in paths
    assert "scripts/run_private_final.py" in paths
    assert "scripts/analyze_private_final.py" in paths
    assert "src/denser/analysis/final_results.py" in paths
    assert "src/denser/experiments/robustness.py" in paths
