from __future__ import annotations

from dataclasses import dataclass


GIB = 1024**3
MAX_CONFIRMATORY_SECONDS = 7 * 24 * 3600
MAX_PROCESS_BYTES = 24 * GIB
MIN_HOST_RESERVE_BYTES = 8 * GIB
MIN_FINAL_SLIDES = 18
MIN_STANDARD_FAMILIES = 2


@dataclass(frozen=True, slots=True)
class FeasibilityEvidence:
    projected_confirmatory_seconds: float
    peak_process_bytes: int
    host_reserve_bytes: int
    free_disk_bytes: int
    preflight_free_disk_bytes: int
    evaluable_final_slides: int
    standard_codec_families: int


@dataclass(frozen=True, slots=True)
class GenerationGateResult:
    passed: bool
    failure_codes: tuple[str, ...]
    required_disk_reserve_bytes: int


def evaluate_generation_gate(evidence: FeasibilityEvidence) -> GenerationGateResult:
    required_disk = max(100 * GIB, int(evidence.preflight_free_disk_bytes * 0.20))
    checks = (
        ("projected_runtime_over_seven_days", evidence.projected_confirmatory_seconds <= MAX_CONFIRMATORY_SECONDS),
        ("process_memory_over_24_gib", evidence.peak_process_bytes <= MAX_PROCESS_BYTES),
        ("host_reserve_below_8_gib", evidence.host_reserve_bytes >= MIN_HOST_RESERVE_BYTES),
        ("disk_reserve_below_policy", evidence.free_disk_bytes >= required_disk),
        ("fewer_than_18_final_slides", evidence.evaluable_final_slides >= MIN_FINAL_SLIDES),
        ("fewer_than_two_standard_families", evidence.standard_codec_families >= MIN_STANDARD_FAMILIES),
    )
    failures = tuple(code for code, passed in checks if not passed)
    return GenerationGateResult(not failures, failures, required_disk)
