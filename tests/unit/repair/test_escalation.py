from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from denser.codecs.lossless import SharedLosslessCodec
from denser.repair.escalate import repair_until_verified
from denser.repair.mask import RepairFailure
from denser.repair.packet_v2 import apply_repair_packet


@dataclass(frozen=True)
class Check:
    passed: bool
    failures: tuple[RepairFailure, ...] = ()


class AlwaysFailVerifier:
    def verify(self, source: np.ndarray, decoded: np.ndarray) -> Check:
        return Check(False)


class ExactVerifier:
    def verify(self, source: np.ndarray, decoded: np.ndarray) -> Check:
        if np.array_equal(source, decoded):
            return Check(True)
        height, width, _ = source.shape
        return Check(False, (RepairFailure(0, 0, width, height, width, height),))


def source() -> np.ndarray:
    values = np.arange(8 * 8 * 3, dtype=np.uint8)
    return values.reshape(8, 8, 3)


def test_unresolved_repair_fails_closed_to_lossless() -> None:
    original = source()
    proposal = np.zeros_like(original)
    result = repair_until_verified(
        original, proposal, AlwaysFailVerifier(), SharedLosslessCodec()
    )
    assert result.status == "fallback"
    np.testing.assert_array_equal(result.decoded, original)
    assert result.breakdown.fallback_signaling > 0


def test_exact_residual_is_verified_and_all_repair_bytes_are_counted() -> None:
    original = source()
    proposal = original.copy()
    proposal[2:4, 2:4] = 0
    failure = RepairFailure(2, 2, 2, 2, image_width=8, image_height=8)

    class LocalVerifier:
        def verify(self, source: np.ndarray, decoded: np.ndarray) -> Check:
            return Check(np.array_equal(source, decoded), (failure,))

    result = repair_until_verified(
        original, proposal, LocalVerifier(), SharedLosslessCodec(), halo_um=0, mpp=0.25
    )
    assert result.status == "verified_repair"
    assert result.stage == "exact_pixel_residual"
    np.testing.assert_array_equal(result.decoded, original)
    assert result.breakdown.repair == len(result.payload)
    np.testing.assert_array_equal(apply_repair_packet(proposal, result.payload), original)


def test_already_verified_proposal_does_not_emit_repair_payload() -> None:
    original = source()
    result = repair_until_verified(
        original, original.copy(), ExactVerifier(), SharedLosslessCodec()
    )
    assert result.status == "verified"
    assert result.breakdown.repair == 0
    assert result.payload == b""


def test_repair_packet_corruption_fails_closed() -> None:
    original = source()
    proposal = original.copy()
    proposal[2:4, 2:4] = 0
    failure = RepairFailure(2, 2, 2, 2, image_width=8, image_height=8)

    class LocalVerifier:
        def verify(self, source: np.ndarray, decoded: np.ndarray) -> Check:
            return Check(np.array_equal(source, decoded), (failure,))

    result = repair_until_verified(
        original, proposal, LocalVerifier(), SharedLosslessCodec(), halo_um=0, mpp=0.25
    )
    damaged = bytearray(result.payload)
    damaged[-1] ^= 1
    with pytest.raises(ValueError):
        apply_repair_packet(proposal, bytes(damaged))
