from __future__ import annotations

from denser.analysis.final_results import FinalSlideResult, analyze_final_results
from denser.experiments.final import FinalPerformanceSummary


def performance(**changes: float) -> FinalPerformanceSummary:
    values = {
        "standard_encoding_seconds": 100.0,
        "denser_encoding_seconds": 400.0,
        "encoding_time_ratio": 4.0,
        "standard_cold_decode_p95_seconds": 0.01,
        "denser_cold_decode_p95_seconds": 0.015,
        "cold_decode_p95_ratio": 1.5,
        "standard_warm_decode_p95_seconds": 0.008,
        "denser_warm_decode_p95_seconds": 0.009,
        "warm_decode_p95_ratio": 1.125,
        "random_probe_observations": 576,
    }
    values.update(changes)
    return FinalPerformanceSummary(**values)


def positive_rows() -> tuple[FinalSlideResult, ...]:
    return tuple(
        FinalSlideResult(
            f"slide-{index:02d}",
            f"project-{index % 6}",
            standard_complete_bytes=1000,
            denser_complete_bytes=750,
            tile_count=100 + index,
        )
        for index in range(18)
    )


def test_final_analysis_applies_slide_bootstrap_and_all_technical_gates() -> None:
    analysis = analyze_final_results(
        positive_rows(),
        performance(),
        standard_codec_families=3,
        acceptance_violations=0,
        independent_random_tile_decode=True,
        full_slide_processing=True,
        seed=20260808,
    )
    assert analysis.statistical_result.bootstrap_unit == "slide"
    assert analysis.statistical_result.slide_count == 18
    assert analysis.scientific_outcome == "positive"
    assert analysis.completeness.encoding_time_ratio == 4.0


def test_final_analysis_cannot_be_positive_when_runtime_gate_misses() -> None:
    analysis = analyze_final_results(
        positive_rows(),
        performance(encoding_time_ratio=10.1),
        standard_codec_families=3,
        acceptance_violations=0,
        independent_random_tile_decode=True,
        full_slide_processing=True,
        seed=20260808,
    )
    assert analysis.scientific_outcome == "inconclusive"
