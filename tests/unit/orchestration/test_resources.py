from __future__ import annotations

import inspect

from denser.orchestration.resources import (
    ExecutionPolicy,
    ResourceReport,
    SourceManifestSummary,
    choose_execution_tier,
)


def test_tier_uses_source_scratch_output_and_reserve() -> None:
    gib = 1024**3
    decision = choose_execution_tier(
        ResourceReport(free_bytes=900 * gib, memory_bytes=32 * gib, cpu_count=8),
        SourceManifestSummary(source_bytes=100 * gib, eligible_slides=90),
        ExecutionPolicy(scratch_multiplier=1.5, output_multiplier=0.5),
    )
    assert decision.required_bytes == (
        100 * gib + decision.scratch + decision.outputs + decision.reserve
    )
    assert decision.reserve == 180 * gib


def test_tier_cannot_depend_on_compression_outcome() -> None:
    assert "observed_reduction" not in inspect.signature(choose_execution_tier).parameters


def test_preflight_can_lower_but_never_raise_resource_caps() -> None:
    gib = 1024**3
    decision = choose_execution_tier(
        ResourceReport(free_bytes=40 * gib, memory_bytes=12 * gib, cpu_count=2),
        SourceManifestSummary(source_bytes=1 * gib, eligible_slides=12),
        ExecutionPolicy(reserve_min_bytes=5 * gib),
    )
    assert decision.cpu_workers == 2
    assert decision.codec_subprocesses <= 2
    assert decision.memory_ceiling_bytes <= 24 * gib
    assert decision.tier == "not_evaluable"
