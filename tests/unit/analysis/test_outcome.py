from __future__ import annotations

from denser.analysis.outcome import CompletionCriteria, classify_scientific_outcome
from denser.analysis.statistics import StatisticalResult


def result(median: float, lower: float, upper: float = 0.3) -> StatisticalResult:
    return StatisticalResult("slide", 18, median, lower, upper, 9, 1000)


def complete(**changes: object) -> CompletionCriteria:
    values = {
        "evaluable_final_slides": 18,
        "standard_codec_families": 2,
        "acceptance_violations": 0,
        "independent_random_tile_decode": True,
        "full_slide_processing": True,
        "encoding_time_ratio": 4.0,
        "cold_decode_p95_ratio": 1.5,
        "warm_decode_p95_ratio": 1.2,
    }
    values.update(changes)
    return CompletionCriteria(**values)


def test_positive_requires_all_primary_conditions() -> None:
    outcome = classify_scientific_outcome(result(median=.20, lower=.08), complete())
    assert outcome == "positive"
    assert classify_scientific_outcome(result(median=.20, lower=.08), complete(acceptance_violations=1)) != "positive"


def test_low_final_count_is_not_evaluable_and_negative_rules_are_exact() -> None:
    assert classify_scientific_outcome(result(.2, .08), complete(evaluable_final_slides=17)) == "not_evaluable"
    assert classify_scientific_outcome(result(.01, -.03, .04), complete()) == "negative"
    assert classify_scientific_outcome(result(.10, .02, .20), complete()) == "inconclusive"


def test_positive_requires_predeclared_runtime_bounds() -> None:
    positive = result(.20, .08)
    assert classify_scientific_outcome(
        positive, complete(encoding_time_ratio=10.01)
    ) == "inconclusive"
    assert classify_scientific_outcome(
        positive, complete(cold_decode_p95_ratio=2.01)
    ) == "inconclusive"
    assert classify_scientific_outcome(
        positive, complete(warm_decode_p95_ratio=2.01)
    ) == "inconclusive"
