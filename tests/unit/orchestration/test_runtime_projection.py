from __future__ import annotations

import pytest

from denser.orchestration.runtime_projection import (
    DevelopmentTimingSample,
    deterministic_sample_indices,
    project_confirmatory_runtime,
)


def _sample(index: int, seconds: tuple[float, ...] = (1.0, 1.5, 2.0)) -> DevelopmentTimingSample:
    return DevelopmentTimingSample(
        slide_key=f"slide-{index}",
        project=f"project-{index}",
        source_bytes=1_000,
        level0_tiles=100,
        tile_pipeline_seconds=seconds,
    )


def test_projection_uses_conservative_tile_density_and_nearest_rank_p95() -> None:
    samples = [_sample(index) for index in range(5)]
    samples[-1] = DevelopmentTimingSample(
        "slide-4", "project-4", 1_000, 200, (2.0, 3.0, 4.0)
    )
    report = project_confirmatory_runtime(
        samples,
        final_source_bytes=10_000,
        worker_count=2,
        safety_factor=1.25,
    )
    assert report.projected_level0_tiles == 2_000
    assert report.p95_tile_pipeline_seconds == 4.0
    assert report.projected_confirmatory_seconds == 5_000.0
    assert report.development_slide_count == 5


def test_projection_requires_five_distinct_development_slides() -> None:
    with pytest.raises(ValueError, match="five distinct"):
        project_confirmatory_runtime(
            [_sample(index) for index in range(4)],
            final_source_bytes=10_000,
            worker_count=2,
        )


@pytest.mark.parametrize("workers", [0, 7])
def test_projection_enforces_declared_worker_limit(workers: int) -> None:
    with pytest.raises(ValueError, match="worker count"):
        project_confirmatory_runtime(
            [_sample(index) for index in range(5)],
            final_source_bytes=10_000,
            worker_count=workers,
        )


def test_projection_requires_measured_scaling_above_two_workers() -> None:
    with pytest.raises(ValueError, match="measured parallel"):
        project_confirmatory_runtime(
            [_sample(index) for index in range(5)],
            final_source_bytes=10_000,
            worker_count=6,
        )


def test_projection_uses_conservative_measured_parallel_speedup() -> None:
    report = project_confirmatory_runtime(
        [_sample(index) for index in range(5)],
        final_source_bytes=10_000,
        worker_count=6,
        measured_parallel_speedup=2.25,
        measured_parallel_tile_seconds=0.9,
        parallel_benchmark_tiles=12,
    )
    assert report.measured_parallel_speedup == 2.25
    assert report.measured_parallel_tile_seconds == 0.9
    assert report.parallel_benchmark_tiles == 12
    assert report.projected_confirmatory_seconds == pytest.approx(
        1_000 * 0.9 * 1.25
    )


def test_projection_stratifies_known_final_bytes_and_measured_project_rates() -> None:
    samples = [_sample(index) for index in range(5)]
    report = project_confirmatory_runtime(
        samples,
        final_source_bytes=15_000,
        final_source_bytes_by_project={f"project-{index}": 3_000 for index in range(5)},
        worker_count=6,
        measured_parallel_speedup=2.0,
        measured_parallel_tile_seconds=9.0,
        measured_parallel_tile_seconds_by_project={
            "project-0": 0.5,
            "project-1": 0.6,
            "project-2": 0.7,
            "project-3": 0.8,
            "project-4": 0.9,
        },
        parallel_benchmark_tiles=40,
    )
    assert report.model_version == "development-project-stratified-measured-scaling-v3"
    assert report.projected_level0_tiles == 1_500
    assert report.measured_parallel_tile_seconds == pytest.approx(0.7)
    assert report.projected_confirmatory_seconds == pytest.approx(1_312.5)

    with pytest.raises(ValueError, match="project coverage"):
        project_confirmatory_runtime(
            samples,
            final_source_bytes=15_000,
            final_source_bytes_by_project={"project-0": 15_000},
            worker_count=6,
            measured_parallel_speedup=2.0,
            measured_parallel_tile_seconds=0.9,
            measured_parallel_tile_seconds_by_project={"project-0": 0.5},
            parallel_benchmark_tiles=40,
        )


def test_runtime_sample_indices_are_deterministic_uniform_without_replacement() -> None:
    first = deterministic_sample_indices(10_000, 64, seed=17, slide_ordinal=3)
    second = deterministic_sample_indices(10_000, 64, seed=17, slide_ordinal=3)
    assert first == second
    assert len(first) == len(set(first)) == 64
    assert min(first) >= 0 and max(first) < 10_000
    assert first != deterministic_sample_indices(10_000, 64, seed=18, slide_ordinal=3)
