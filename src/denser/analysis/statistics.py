from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SlidePair:
    slide_key: str
    project: str
    denser_bytes: int
    standard_bytes: int
    tile_count: int

    def __post_init__(self) -> None:
        if not self.slide_key or not self.project or min(self.denser_bytes, self.standard_bytes, self.tile_count) <= 0:
            raise ValueError("paired slide row is incomplete")

    @property
    def reduction(self) -> float:
        return 1.0 - self.denser_bytes / self.standard_bytes


@dataclass(frozen=True, slots=True)
class StatisticalConfig:
    bootstrap_replicates: int = 10_000
    confidence: float = 0.95

    def __post_init__(self) -> None:
        if self.bootstrap_replicates < 100 or not 0 < self.confidence < 1:
            raise ValueError("statistical configuration is invalid")


@dataclass(frozen=True, slots=True)
class StatisticalResult:
    bootstrap_unit: str
    slide_count: int
    median_reduction: float
    lower_bound: float
    upper_bound: float
    seed: int
    bootstrap_replicates: int


def paired_slide_analysis(
    rows: tuple[SlidePair, ...] | list[SlidePair],
    config: StatisticalConfig,
    seed: int,
) -> StatisticalResult:
    if not rows:
        raise ValueError("paired slide analysis requires at least one slide")
    ordered = sorted(rows, key=lambda row: (row.project, row.slide_key))
    if len({row.slide_key for row in ordered}) != len(ordered):
        raise ValueError("slide rows must be unique")
    by_project: dict[str, list[float]] = {}
    for row in ordered:
        by_project.setdefault(row.project, []).append(row.reduction)
    rng = np.random.default_rng(seed)
    medians = np.empty(config.bootstrap_replicates, dtype=np.float64)
    project_names = sorted(by_project)
    for index in range(config.bootstrap_replicates):
        sampled: list[float] = []
        for project in project_names:
            values = np.asarray(by_project[project], dtype=np.float64)
            sampled.extend(rng.choice(values, size=len(values), replace=True).tolist())
        medians[index] = np.median(sampled)
    alpha = (1.0 - config.confidence) / 2
    reductions = [row.reduction for row in ordered]
    return StatisticalResult(
        "slide",
        len(ordered),
        round(float(np.median(reductions)), 12),
        round(float(np.quantile(medians, alpha)), 12),
        round(float(np.quantile(medians, 1 - alpha)), 12),
        seed,
        config.bootstrap_replicates,
    )
