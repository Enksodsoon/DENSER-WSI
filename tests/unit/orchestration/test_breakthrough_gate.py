from __future__ import annotations

from dataclasses import replace

from denser.orchestration.breakthrough import FeasibilityEvidence, evaluate_generation_gate


GIB = 1024**3


def passing() -> FeasibilityEvidence:
    return FeasibilityEvidence(
        projected_confirmatory_seconds=6 * 24 * 3600,
        peak_process_bytes=20 * GIB,
        host_reserve_bytes=10 * GIB,
        free_disk_bytes=500 * GIB,
        preflight_free_disk_bytes=600 * GIB,
        evaluable_final_slides=18,
        standard_codec_families=4,
    )


def test_generation_gate_requires_all_resource_and_scientific_prerequisites() -> None:
    assert evaluate_generation_gate(passing()).passed
    failures = (
        replace(passing(), projected_confirmatory_seconds=8 * 24 * 3600),
        replace(passing(), peak_process_bytes=25 * GIB),
        replace(passing(), host_reserve_bytes=7 * GIB),
        replace(passing(), free_disk_bytes=119 * GIB),
        replace(passing(), evaluable_final_slides=17),
        replace(passing(), standard_codec_families=1),
    )
    assert all(not evaluate_generation_gate(item).passed for item in failures)


def test_disk_reserve_is_maximum_of_100_gib_and_twenty_percent() -> None:
    result = evaluate_generation_gate(passing())
    assert result.required_disk_reserve_bytes == 120 * GIB

