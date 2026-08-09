from __future__ import annotations

import numpy as np
import pytest

from denser.repair.mask import build_union_repair_mask, RepairFailure
from denser.repair.packet_v2 import apply_repair_packet
from denser.repair.transform_overlay import (
    apply_transform_overlay,
    encode_transform_overlay,
)


def _fixture() -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[:16, :16]
    source = np.stack(
        ((x * 11 + y * 3) % 256, (x * 5 + 80) % 256, (y * 13 + 20) % 256),
        axis=2,
    ).astype(np.uint8)
    proposal = source.copy()
    proposal[:8, :8] = np.clip(proposal[:8, :8].astype(np.int16) + 20, 0, 255)
    return source, proposal.astype(np.uint8)


def test_transform_overlay_is_deterministic_compact_and_improves_error() -> None:
    source, proposal = _fixture()
    failure = RepairFailure(0, 0, 8, 8, 16, 16)
    mask = build_union_repair_mask((failure,), halo_um=0, mpp=0.25)
    first = encode_transform_overlay(
        source, proposal, mask, coefficients_per_block=4, quantization_step=1.0
    )
    second = encode_transform_overlay(
        source.copy(), proposal.copy(), mask, coefficients_per_block=4, quantization_step=1.0
    )
    repaired = apply_transform_overlay(proposal, first)
    np.testing.assert_array_equal(apply_repair_packet(proposal, first), repaired)
    assert first == second
    assert len(first) < mask.pixel_count * 3
    assert np.mean(np.abs(source.astype(float) - repaired.astype(float))) < np.mean(
        np.abs(source.astype(float) - proposal.astype(float))
    )
    np.testing.assert_array_equal(repaired[~mask.pixels], proposal[~mask.pixels])


def test_dc_overlay_exactly_repairs_constant_block_channel_offsets() -> None:
    source = np.full((8, 8, 3), (80, 120, 160), dtype=np.uint8)
    proposal = np.full((8, 8, 3), (70, 100, 130), dtype=np.uint8)
    mask = build_union_repair_mask((RepairFailure(0, 0, 8, 8, 8, 8),), 0, 0.25)
    encoded = encode_transform_overlay(
        source,
        proposal,
        mask,
        coefficients_per_block=0,
        quantization_step=1.0,
        block_size=8,
    )
    np.testing.assert_array_equal(apply_transform_overlay(proposal, encoded), source)


@pytest.mark.parametrize("mutation", ["magic", "digest", "trailing"])
def test_transform_overlay_rejects_corruption(mutation: str) -> None:
    source, proposal = _fixture()
    mask = build_union_repair_mask((RepairFailure(0, 0, 8, 8, 16, 16),), 0, 0.25)
    encoded = bytearray(
        encode_transform_overlay(source, proposal, mask, coefficients_per_block=4, quantization_step=2.0)
    )
    if mutation == "magic":
        encoded[0] ^= 1
    elif mutation == "digest":
        encoded[-1] ^= 1
    else:
        encoded.append(0)
    with pytest.raises(ValueError):
        apply_transform_overlay(proposal, bytes(encoded))
