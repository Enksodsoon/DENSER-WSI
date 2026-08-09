from __future__ import annotations

import numpy as np
import pytest

from denser.method.allocation_map_v2 import (
    EvidenceAllocationMapV2,
    build_evidence_allocation_map,
)


def test_allocation_map_is_compact_deterministic_and_reconstructs_steps() -> None:
    sensitivity = np.ones((16, 16, 3), dtype=np.float64)
    sensitivity[:8, :8] = 100.0
    first = build_evidence_allocation_map(sensitivity)
    second = build_evidence_allocation_map(sensitivity.copy())

    assert first.encode() == second.encode()
    assert len(first.encode()) < sensitivity.size * 4 // 10
    assert EvidenceAllocationMapV2.decode(first.encode()) == first
    steps = first.coefficient_steps(4.0, (16, 16, 3))
    assert steps.shape == sensitivity.shape
    assert steps[:8, :8].mean() < steps[8:, 8:].mean()


@pytest.mark.parametrize("mutation", ["magic", "length", "digest", "trailing"])
def test_allocation_map_rejects_noncanonical_or_corrupt_bytes(mutation: str) -> None:
    encoded = bytearray(build_evidence_allocation_map(np.ones((8, 8, 3))).encode())
    if mutation == "magic":
        encoded[0] ^= 1
    elif mutation == "length":
        encoded[14:18] = (999999).to_bytes(4, "big")
    elif mutation == "digest":
        encoded[-1] ^= 1
    else:
        encoded.append(0)
    with pytest.raises(ValueError):
        EvidenceAllocationMapV2.decode(bytes(encoded))
