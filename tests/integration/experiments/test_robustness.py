from __future__ import annotations

from pathlib import Path

from denser.experiments.robustness import RobustnessConfig, run_robustness, sha256_tree


def test_robustness_cannot_modify_primary_results(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "result.bin").write_bytes(b"immutable-primary-result")
    before = sha256_tree(primary)
    report = run_robustness(RobustnessConfig(tmp_path / "secondary"), primary)
    assert sha256_tree(primary) == before
    assert report.primary_tree_before == report.primary_tree_after == before
    assert report.analysis_scope == "secondary_exploratory"


def test_robustness_records_missing_optional_inputs(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    report = run_robustness(RobustnessConfig(tmp_path / "secondary"), primary)
    assert report.status == "not_evaluable"
    assert "alternate_mpp" in report.missing_analyses
    assert report.primary_files_examined == 0
