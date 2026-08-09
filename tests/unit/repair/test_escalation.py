from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from denser.codecs.lossless import SharedLosslessCodec
from denser.repair.escalate import repair_until_verified
from denser.repair.mask import RepairFailure, build_union_repair_mask
from denser.repair.packet_v2 import (
    apply_repair_packet,
    encode_composite_repair_packet,
    encode_repair_packet,
)
from denser.repair.residual import encode_exact_residual


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


def test_byte_dominated_repair_stages_are_not_reverified() -> None:
    original = source()
    proposal = np.zeros_like(original)
    failure = RepairFailure(0, 0, 8, 8, image_width=8, image_height=8)

    class CountingVerifier:
        calls = 0

        def verify(self, source: np.ndarray, decoded: np.ndarray) -> Check:
            self.calls += 1
            return Check(False, (failure,))

    verifier = CountingVerifier()
    codec = SharedLosslessCodec()
    result = repair_until_verified(
        original,
        proposal,
        verifier,
        codec,
        initial_verification=Check(False, (failure,)),
        encoded_fallback=codec.encode(original),
        maximum_repair_bytes=1,
    )
    assert result.status == "fallback"
    assert verifier.calls == 0


def test_compact_dc_overlay_precedes_exact_pixel_residual() -> None:
    generator = np.random.default_rng(19)
    original = generator.integers(80, 180, (32, 32, 3), dtype=np.uint8)
    proposal = (original.astype(np.int16) - np.array((10, 20, 30))).astype(np.uint8)
    result = repair_until_verified(
        original, proposal, ExactVerifier(), SharedLosslessCodec(), halo_um=0
    )
    assert result.status == "verified_repair"
    assert result.stage == "finer_local_quantization"
    assert result.payload.startswith(b"R2TO")
    np.testing.assert_array_equal(apply_repair_packet(proposal, result.payload), original)


def test_composite_repair_packet_applies_canonical_parts_and_rejects_corruption() -> None:
    original = source()
    proposal = np.zeros_like(original)
    first_mask = build_union_repair_mask(
        (RepairFailure(0, 0, 4, 8, 8, 8),), 0, 0.25
    )
    second_mask = build_union_repair_mask(
        (RepairFailure(4, 0, 4, 8, 8, 8),), 0, 0.25
    )
    first = proposal.copy()
    first[first_mask.pixels] = original[first_mask.pixels]
    second = first.copy()
    second[second_mask.pixels] = original[second_mask.pixels]
    payload = encode_composite_repair_packet(
        (encode_repair_packet(first_mask, first), encode_repair_packet(second_mask, second))
    )
    assert payload.startswith(b"R2CP")
    np.testing.assert_array_equal(apply_repair_packet(proposal, payload), original)
    damaged = bytearray(payload)
    damaged[-1] ^= 1
    with pytest.raises(ValueError):
        apply_repair_packet(proposal, bytes(damaged))


def test_exact_repair_uses_smaller_signed_delta_encoding_when_available() -> None:
    original = np.random.default_rng(42).integers(
        1, 256, (64, 64, 3), dtype=np.uint8
    )
    proposal = (original - 1).astype(np.uint8)
    mask = build_union_repair_mask(
        (RepairFailure(0, 0, 64, 64, 64, 64),), 0, 0.25
    )
    pixel_packet = encode_repair_packet(mask, original)
    delta_packet = encode_repair_packet(mask, original, base=proposal)
    assert len(delta_packet) < len(pixel_packet)
    np.testing.assert_array_equal(
        apply_repair_packet(proposal, delta_packet), original
    )


def test_repair_packet_reuses_precomputed_exact_residual_byte_identically() -> None:
    original = np.random.default_rng(43).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    proposal = original.copy()
    proposal[:16, :16] //= 2
    mask = build_union_repair_mask(
        (RepairFailure(0, 0, 16, 16, 32, 32),), 0, 0.25
    )
    residual = encode_exact_residual(original, mask)
    expected = encode_repair_packet(mask, original, base=proposal)
    observed = encode_repair_packet(
        mask,
        original,
        base=proposal,
        precomputed_exact_residual=residual,
    )
    assert observed == expected


def test_critical_exact_repair_can_precede_visual_transform_repair() -> None:
    original = np.random.default_rng(41).integers(
        60, 220, (32, 32, 3), dtype=np.uint8
    )
    proposal = np.clip(original.astype(np.int16) - 20, 0, 255).astype(np.uint8)
    critical = RepairFailure(0, 0, 16, 16, 32, 32, ("rare_event_sentinels",))
    visual = RepairFailure(16, 0, 16, 16, 32, 32, ("visual",))

    class StagedVerifier:
        def verify(self, source: np.ndarray, decoded: np.ndarray) -> Check:
            critical_exact = np.array_equal(source[:16, :16], decoded[:16, :16])
            visual_improved = float(decoded[:16, 16:].mean()) > float(
                proposal[:16, 16:].mean()
            )
            failures = []
            if not critical_exact:
                failures.append(critical)
            if not visual_improved:
                failures.append(visual)
            return Check(not failures, tuple(failures))

    result = repair_until_verified(
        original,
        proposal,
        StagedVerifier(),
        SharedLosslessCodec(),
        halo_um=0,
        mpp=0.25,
    )
    assert result.status == "verified_repair"
    assert result.stage == "critical_exact_then_finer_local_quantization"
    assert result.payload.startswith(b"R2CP")
    decoded = apply_repair_packet(proposal, result.payload)
    np.testing.assert_array_equal(decoded, result.decoded)
    assert StagedVerifier().verify(original, decoded).passed
