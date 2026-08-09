from __future__ import annotations

import math
import hashlib
import heapq
import struct
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
    measured_parallel_speedup: float
    measured_parallel_tile_seconds: float
    parallel_benchmark_tiles: int
    safety_factor: float
    projected_confirmatory_seconds: float


def deterministic_sample_indices(
    total: int, count: int, *, seed: int, slide_ordinal: int
) -> tuple[int, ...]:
    if total <= 0 or count <= 0 or count > total:
        raise ValueError("runtime sample count must fit the level-0 grid")
    if seed < 0 or slide_ordinal < 0:
        raise ValueError("runtime sample seed and slide ordinal must be non-negative")

    def key(index: int) -> bytes:
        return hashlib.sha256(
            struct.pack(">QQQ", seed, slide_ordinal, index)
        ).digest()

    return tuple(sorted(heapq.nsmallest(count, range(total), key=key)))


def _nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def project_confirmatory_runtime(
    samples: list[DevelopmentTimingSample],
    *,
    final_source_bytes: int,
    final_source_bytes_by_project: dict[str, int] | None = None,
    worker_count: int,
    measured_parallel_speedup: float | None = None,
    measured_parallel_tile_seconds: float | None = None,
    measured_parallel_tile_seconds_by_project: dict[str, float] | None = None,
    parallel_benchmark_tiles: int = 0,
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
    if worker_count < 1 or worker_count > 6:
        raise ValueError("worker count must remain between one and six")
    if worker_count > 2 and (
        measured_parallel_speedup is None or measured_parallel_tile_seconds is None
    ):
        raise ValueError("measured parallel scaling is required above two workers")
    if measured_parallel_speedup is not None:
        if (
            not math.isfinite(measured_parallel_speedup)
            or measured_parallel_speedup <= 1
            or measured_parallel_speedup > worker_count
        ):
            raise ValueError("measured parallel speedup is outside the worker bounds")
        if parallel_benchmark_tiles < 8:
            raise ValueError("measured parallel scaling requires at least eight tiles")
    elif parallel_benchmark_tiles:
        raise ValueError("parallel benchmark tiles require measured parallel speedup")
    if measured_parallel_tile_seconds is not None and (
        not math.isfinite(measured_parallel_tile_seconds)
        or measured_parallel_tile_seconds <= 0
    ):
        raise ValueError("measured parallel tile time must be positive and finite")
    project_stratified = (
        final_source_bytes_by_project is not None
        or measured_parallel_tile_seconds_by_project is not None
    )
    if project_stratified:
        if (
            final_source_bytes_by_project is None
            or measured_parallel_tile_seconds_by_project is None
            or measured_parallel_speedup is None
        ):
            raise ValueError("project-stratified projection requires matched scaling inputs")
        projects = {sample.project for sample in samples}
        if (
            set(final_source_bytes_by_project) != projects
            or set(measured_parallel_tile_seconds_by_project) != projects
        ):
            raise ValueError("project-stratified projection requires exact project coverage")
        if (
            any(value <= 0 for value in final_source_bytes_by_project.values())
            or sum(final_source_bytes_by_project.values()) != final_source_bytes
            or any(
                not math.isfinite(value) or value <= 0
                for value in measured_parallel_tile_seconds_by_project.values()
            )
        ):
            raise ValueError("project-stratified projection inputs are invalid")
    if not math.isfinite(safety_factor) or safety_factor < 1:
        raise ValueError("runtime safety factor must be finite and at least one")
    density = max(sample.level0_tiles / sample.source_bytes for sample in samples)
    projected_tiles = math.ceil(final_source_bytes * density)
    p95_seconds = _nearest_rank_p95(
        [value for sample in samples for value in sample.tile_pipeline_seconds]
    )
    effective_speedup = measured_parallel_speedup or float(worker_count)
    effective_tile_seconds = (
        measured_parallel_tile_seconds
        if measured_parallel_tile_seconds is not None
        else p95_seconds / effective_speedup
    )
    model_version = (
        "development-max-density-p95-measured-scaling-v2"
        if measured_parallel_speedup is not None
        else "development-max-density-p95-v1"
    )
    if project_stratified:
        assert final_source_bytes_by_project is not None
        assert measured_parallel_tile_seconds_by_project is not None
        project_densities = {
            project: max(
                sample.level0_tiles / sample.source_bytes
                for sample in samples
                if sample.project == project
            )
            for project in final_source_bytes_by_project
        }
        project_tiles = {
            project: math.ceil(
                final_source_bytes_by_project[project] * project_densities[project]
            )
            for project in final_source_bytes_by_project
        }
        projected_tiles = sum(project_tiles.values())
        projected_seconds_without_safety = sum(
            project_tiles[project]
            * measured_parallel_tile_seconds_by_project[project]
            for project in project_tiles
        )
        effective_tile_seconds = projected_seconds_without_safety / projected_tiles
        projected_seconds = projected_seconds_without_safety * safety_factor
        model_version = "development-project-stratified-measured-scaling-v3"
    else:
        projected_seconds = projected_tiles * effective_tile_seconds * safety_factor
    return RuntimeProjection(
        model_version,
        len({sample.slide_key for sample in samples}),
        projected_tiles,
        density,
        p95_seconds,
        worker_count,
        effective_speedup,
        effective_tile_seconds,
        parallel_benchmark_tiles,
        safety_factor,
        projected_seconds,
    )
