from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DevelopmentTimingSample:
    slide_key: str
    project: str
    source_bytes: int
    level0_tiles: int
    tile_pipeline_seconds: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.slide_key or not self.project:
            raise ValueError("development timing sample requires slide and project keys")
        if self.source_bytes <= 0 or self.level0_tiles <= 0:
            raise ValueError("development timing size and tile count must be positive")
        if not self.tile_pipeline_seconds or any(
            not math.isfinite(value) or value <= 0 for value in self.tile_pipeline_seconds
        ):
            raise ValueError("development tile timings must be positive and finite")


@dataclass(frozen=True, slots=True)
class RuntimeProjection:
    model_version: str
    development_slide_count: int
    projected_level0_tiles: int
    maximum_tiles_per_source_byte: float
    p95_tile_pipeline_seconds: float
    worker_count: int
    safety_factor: float
    projected_confirmatory_seconds: float


def _nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def project_confirmatory_runtime(
    samples: list[DevelopmentTimingSample],
    *,
    final_source_bytes: int,
    worker_count: int,
    safety_factor: float = 1.25,
) -> RuntimeProjection:
    """Project full final runtime without opening final pixels.

    The model deliberately combines the largest observed level-0 tile density
    with the nearest-rank p95 complete-pipeline tile time and a fixed safety
    multiplier. This is conservative even when those maxima occur on different
    development slides.
    """
    if len({sample.slide_key for sample in samples}) < 5:
        raise ValueError("projection requires five distinct development slides")
    if final_source_bytes <= 0:
        raise ValueError("final source byte total must be positive")
    if worker_count not in (1, 2):
        raise ValueError("worker count must respect the measured two-worker host limit")
    if not math.isfinite(safety_factor) or safety_factor < 1:
        raise ValueError("runtime safety factor must be finite and at least one")
    density = max(sample.level0_tiles / sample.source_bytes for sample in samples)
    projected_tiles = math.ceil(final_source_bytes * density)
    p95_seconds = _nearest_rank_p95(
        [value for sample in samples for value in sample.tile_pipeline_seconds]
    )
    projected_seconds = projected_tiles * p95_seconds * safety_factor / worker_count
    return RuntimeProjection(
        "development-max-density-p95-v1",
        len({sample.slide_key for sample in samples}),
        projected_tiles,
        density,
        p95_seconds,
        worker_count,
        safety_factor,
        projected_seconds,
    )
