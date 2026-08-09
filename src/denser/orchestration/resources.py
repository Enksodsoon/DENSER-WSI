from __future__ import annotations

from dataclasses import dataclass


GIB = 1024**3


@dataclass(frozen=True, slots=True)
class ResourceReport:
    free_bytes: int
    memory_bytes: int
    cpu_count: int

    def __post_init__(self) -> None:
        if min(self.free_bytes, self.memory_bytes, self.cpu_count) <= 0:
            raise ValueError("resource values must be positive")


@dataclass(frozen=True, slots=True)
class SourceManifestSummary:
    source_bytes: int
    eligible_slides: int

    def __post_init__(self) -> None:
        if self.source_bytes < 0 or self.eligible_slides < 0:
            raise ValueError("manifest summary values cannot be negative")


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    scratch_multiplier: float = 1.5
    output_multiplier: float = 0.5
    reserve_min_bytes: int = 100 * GIB
    reserve_fraction: float = 0.20
    preferred_slides: int = 66
    reduced_slides: int = 36
    max_cpu_workers: int = 6
    max_codec_subprocesses: int = 2
    max_memory_bytes: int = 24 * GIB
    host_memory_reserve_bytes: int = 8 * GIB

    def __post_init__(self) -> None:
        if min(self.scratch_multiplier, self.output_multiplier) < 0:
            raise ValueError("storage multipliers cannot be negative")
        if not 0 <= self.reserve_fraction <= 1:
            raise ValueError("reserve fraction must be between zero and one")


@dataclass(frozen=True, slots=True)
class TierDecision:
    tier: str
    source: int
    scratch: int
    outputs: int
    reserve: int
    required_bytes: int
    cpu_workers: int
    codec_subprocesses: int
    memory_ceiling_bytes: int
    reason: str


def choose_execution_tier(
    resource_report: ResourceReport,
    source_manifest: SourceManifestSummary,
    policy: ExecutionPolicy,
) -> TierDecision:
    source = source_manifest.source_bytes
    scratch = int(source * policy.scratch_multiplier)
    outputs = int(source * policy.output_multiplier)
    reserve = max(policy.reserve_min_bytes, int(resource_report.free_bytes * policy.reserve_fraction))
    required = source + scratch + outputs + reserve
    disk_sufficient = resource_report.free_bytes >= required
    if disk_sufficient and source_manifest.eligible_slides >= policy.preferred_slides:
        tier, reason = "preferred", "preferred sample and storage requirements satisfied"
    elif disk_sufficient and source_manifest.eligible_slides >= policy.reduced_slides:
        tier, reason = "reduced_conclusive", "reduced conclusive sample and storage requirements satisfied"
    else:
        tier = "not_evaluable"
        reason = "insufficient eligible slides" if disk_sufficient else "insufficient preflight storage"
    cpu_workers = min(policy.max_cpu_workers, resource_report.cpu_count)
    codec_subprocesses = min(policy.max_codec_subprocesses, cpu_workers)
    memory_ceiling = max(
        0,
        min(policy.max_memory_bytes, resource_report.memory_bytes - policy.host_memory_reserve_bytes),
    )
    return TierDecision(
        tier,
        source,
        scratch,
        outputs,
        reserve,
        required,
        cpu_workers,
        codec_subprocesses,
        memory_ceiling,
        reason,
    )
