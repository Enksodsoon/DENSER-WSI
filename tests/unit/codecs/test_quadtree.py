from __future__ import annotations

import numpy as np
import pytest

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.quadtree import (
    QuadtreeAllocationMap,
    build_jpeg_quadtree_candidate,
    build_jpeg_quadtree_candidates,
    build_jpegxl_quadtree_candidate,
    build_jpegxl_quadtree_candidates,
    decode_jpegxl_quadtree_candidate,
    decode_jpeg_quadtree_candidate,
)


class LosslessLeafCodec:
    def __init__(self, distance: float) -> None:
        self.distance = distance

    def encode(self, rgb: np.ndarray) -> EncodedCandidate:
        return SharedLosslessCodec().encode(rgb)

    def decode(self, payload: bytes, shape: tuple[int, int, int]) -> np.ndarray:
        return SharedLosslessCodec().decode(payload, shape)


def test_quadtree_candidate_round_trips_and_signals_varying_leaf_quality() -> None:
    rgb = np.arange(32 * 32 * 3, dtype=np.uint8).reshape(32, 32, 3)
    sensitivity = np.ones_like(rgb, dtype=np.float64)
    sensitivity[:16, :16] = np.indices((16, 16)).sum(axis=0)[..., None] + 1
    candidate = build_jpegxl_quadtree_candidate(
        rgb, sensitivity, min_leaf=8, codec_factory=LosslessLeafCodec
    )
    allocation = QuadtreeAllocationMap.decode(candidate.allocation_map)
    assert len(allocation.leaves) > 1
    assert len({leaf.quality_code for leaf in allocation.leaves}) > 1
    decoded = decode_jpegxl_quadtree_candidate(
        candidate.payload, candidate.allocation_map, codec_factory=LosslessLeafCodec
    )
    np.testing.assert_array_equal(decoded, rgb)


def test_quadtree_allocation_rejects_corruption_and_noncoverage() -> None:
    rgb = np.zeros((16, 16, 3), dtype=np.uint8)
    candidate = build_jpegxl_quadtree_candidate(
        rgb, np.ones_like(rgb, dtype=np.float64), min_leaf=8, codec_factory=LosslessLeafCodec
    )
    damaged = bytearray(candidate.allocation_map)
    damaged[-1] ^= 1
    with pytest.raises(ValueError):
        QuadtreeAllocationMap.decode(bytes(damaged))


def test_quadtree_grid_predeclares_increasingly_conservative_allocations() -> None:
    rgb = np.arange(32 * 32 * 3, dtype=np.uint8).reshape(32, 32, 3)
    sensitivity = np.ones_like(rgb, dtype=np.float64)
    sensitivity[:16, :16] = np.indices((16, 16)).sum(axis=0)[..., None] + 1
    candidates = build_jpegxl_quadtree_candidates(
        rgb,
        sensitivity,
        min_leaf=8,
        codec_factory=LosslessLeafCodec,
    )
    assert len(candidates) == 4
    assert len({candidate.profile_id for candidate in candidates}) == 4
    high_quality_counts = []
    for candidate in candidates:
        allocation = QuadtreeAllocationMap.decode(candidate.allocation_map)
        high_quality_counts.append(
            sum(leaf.quality_code == 0 for leaf in allocation.leaves)
        )
        decoded = decode_jpegxl_quadtree_candidate(
            candidate.payload,
            candidate.allocation_map,
            codec_factory=LosslessLeafCodec,
        )
        np.testing.assert_array_equal(decoded, rgb)
    assert high_quality_counts == sorted(high_quality_counts)


def test_jpeg_quadtree_family_round_trips_and_has_frozen_policy_grid() -> None:
    rgb = np.arange(32 * 32 * 3, dtype=np.uint8).reshape(32, 32, 3)
    sensitivity = np.ones_like(rgb, dtype=np.float64)
    sensitivity[:16, :16] = np.indices((16, 16)).sum(axis=0)[..., None] + 1
    candidate = build_jpeg_quadtree_candidate(
        rgb, sensitivity, min_leaf=8, codec_factory=LosslessLeafCodec
    )
    decoded = decode_jpeg_quadtree_candidate(
        candidate.payload,
        candidate.allocation_map,
        codec_factory=LosslessLeafCodec,
    )
    np.testing.assert_array_equal(decoded, rgb)
    candidates = build_jpeg_quadtree_candidates(
        rgb, sensitivity, min_leaf=8, codec_factory=LosslessLeafCodec
    )
    assert len(candidates) == 4
    assert all(item.codec_id == "denser-quadtree-jpeg-v2" for item in candidates)
    assert len({item.profile_id for item in candidates}) == 4
