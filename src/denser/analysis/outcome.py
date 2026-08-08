from __future__ import annotations

from dataclasses import dataclass

from denser.analysis.statistics import StatisticalResult


@dataclass(frozen=True, slots=True)
class CompletionCriteria:
    evaluable_final_slides: int
    standard_codec_families: int
    acceptance_violations: int
    independent_random_tile_decode: bool
    full_slide_processing: bool


def classify_scientific_outcome(
    result: StatisticalResult,
    completeness: CompletionCriteria,
) -> str:
    evaluable = (
        completeness.evaluable_final_slides >= 18
        and completeness.standard_codec_families >= 2
        and completeness.independent_random_tile_decode
        and completeness.full_slide_processing
    )
    if not evaluable:
        return "not_evaluable"
    if (
        completeness.acceptance_violations == 0
        and result.median_reduction >= 0.15
        and result.lower_bound > 0.05
    ):
        return "positive"
    if result.upper_bound <= 0.05 or result.median_reduction <= 0:
        return "negative"
    return "inconclusive"
