from __future__ import annotations

import pytest

from denser.orchestration.runtime_projection import (
    DevelopmentTimingSample,
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


@pytest.mark.parametrize("workers", [0, 3])
def test_projection_enforces_measured_two_worker_host_limit(workers: int) -> None:
    with pytest.raises(ValueError, match="worker count"):
        project_confirmatory_runtime(
            [_sample(index) for index in range(5)],
            final_source_bytes=10_000,
            worker_count=workers,
        )
