from __future__ import annotations

from denser.analysis.statistics import SlidePair, StatisticalConfig, paired_slide_analysis


def three_slides_many_tiles() -> tuple[SlidePair, ...]:
    return (
        SlidePair("s1", "A", 80, 100, 10000),
        SlidePair("s2", "A", 70, 100, 20000),
        SlidePair("s3", "B", 90, 100, 30000),
    )


def test_bootstrap_resamples_slides_not_tiles() -> None:
    result = paired_slide_analysis(three_slides_many_tiles(), StatisticalConfig(200), seed=9)
    assert result.bootstrap_unit == "slide"
    assert result.slide_count == 3
    assert result.median_reduction == 0.2


def test_project_stratified_bootstrap_is_seed_deterministic() -> None:
    first = paired_slide_analysis(three_slides_many_tiles(), StatisticalConfig(200), seed=9)
    second = paired_slide_analysis(tuple(reversed(three_slides_many_tiles())), StatisticalConfig(200), seed=9)
    assert first == second
