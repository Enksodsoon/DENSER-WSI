from __future__ import annotations

from pathlib import Path

from denser.container.mcv1 import McV1Reader
from denser.experiments.synthetic import SyntheticValidationConfig, run_synthetic_validation
from denser.synthetic.histology import SyntheticSlideSpec, generate_synthetic_slide


def small_config(tmp_path: Path) -> SyntheticValidationConfig:
    return SyntheticValidationConfig(
        output_root=tmp_path,
        slide_specs=(SyntheticSlideSpec(width=64, height=64, tile_size=32),),
        seed=314,
    )


def test_synthetic_slide_runs_all_portfolios_into_mcv1(tmp_path: Path) -> None:
    report = run_synthetic_validation(small_config(tmp_path))
    assert report.methods == {"standard", "uniform", "denser"}
    assert all(row.complete_bytes == row.path.stat().st_size for row in report.slides)
    assert report.unresolved_acceptance_violations == 0
    assert report.fallback_exercised
    assert report.repair_exercised
    assert report.corruption_rejected
    assert report.resume_replayed_only_uncommitted
    for row in report.slides:
        assert row.tile_count == 4
        assert McV1Reader(row.path).byte_ledger().complete_bytes == row.complete_bytes


def test_synthetic_histology_is_seed_deterministic_and_contains_controls() -> None:
    spec = SyntheticSlideSpec(width=64, height=64, tile_size=32)
    first = generate_synthetic_slide(spec, seed=7)
    second = generate_synthetic_slide(spec, seed=7)
    assert first.sha256 == second.sha256
    assert first.feature_counts["nuclei"] > 0
    assert first.feature_counts["glands"] > 0
    assert first.feature_counts["rare_dark_objects"] > 0
    assert first.perturbations == (
        "nuclear_edge_blur",
        "small_object_deletion",
        "local_colour_collapse",
    )
