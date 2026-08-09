from __future__ import annotations

from dataclasses import dataclass

from denser.analysis.outcome import CompletionCriteria, classify_scientific_outcome
from denser.analysis.statistics import (
    SlidePair,
    StatisticalConfig,
    StatisticalResult,
    paired_slide_analysis,
)
from denser.experiments.final import FinalPerformanceSummary


@dataclass(frozen=True, slots=True)
class FinalSlideResult:
    slide_key: str
    project: str
    standard_complete_bytes: int
    denser_complete_bytes: int
    tile_count: int

    def __post_init__(self) -> None:
        if (
            not self.slide_key
            or not self.project
            or min(
                self.standard_complete_bytes,
                self.denser_complete_bytes,
                self.tile_count,
            )
            <= 0
        ):
            raise ValueError("final slide result is incomplete")


@dataclass(frozen=True, slots=True)
class FinalAnalysisResult:
    statistical_result: StatisticalResult
    completeness: CompletionCriteria
    scientific_outcome: str


def analyze_final_results(
    rows: tuple[FinalSlideResult, ...],
    performance: FinalPerformanceSummary,
    *,
    standard_codec_families: int,
    acceptance_violations: int,
    independent_random_tile_decode: bool,
    full_slide_processing: bool,
    seed: int,
    bootstrap_replicates: int = 10_000,
) -> FinalAnalysisResult:
    pairs = tuple(
        SlidePair(
            row.slide_key,
            row.project,
            row.denser_complete_bytes,
            row.standard_complete_bytes,
            row.tile_count,
        )
        for row in rows
    )
    statistical = paired_slide_analysis(
        pairs,
        StatisticalConfig(bootstrap_replicates),
        seed,
    )
    completeness = CompletionCriteria(
        evaluable_final_slides=len(rows),
        standard_codec_families=standard_codec_families,
        acceptance_violations=acceptance_violations,
        independent_random_tile_decode=independent_random_tile_decode,
        full_slide_processing=full_slide_processing,
        encoding_time_ratio=performance.encoding_time_ratio,
        cold_decode_p95_ratio=performance.cold_decode_p95_ratio,
        warm_decode_p95_ratio=performance.warm_decode_p95_ratio,
    )
    return FinalAnalysisResult(
        statistical,
        completeness,
        classify_scientific_outcome(statistical, completeness),
    )
