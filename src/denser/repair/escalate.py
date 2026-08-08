from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from denser.codecs.lossless import SharedLosslessCodec
from denser.core.models import ByteBreakdown
from denser.repair.mask import RepairFailure, build_union_repair_mask
from denser.repair.packet_v2 import encode_repair_packet
from denser.repair.residual import apply_exact_residual, encode_exact_residual


class RepairVerifier(Protocol):
    def verify(self, source: np.ndarray, decoded: np.ndarray) -> Any: ...


@dataclass(frozen=True, slots=True)
class RepairResult:
    status: str
    stage: str
    decoded: np.ndarray
    breakdown: ByteBreakdown
    payload: bytes = b""
    mask_bytes: int = 0
    overlay_bytes: int = 0
    residual_bytes: int = 0


def _blend_overlay(
    proposal: np.ndarray, source: np.ndarray, mask: np.ndarray, numerator: int
) -> tuple[np.ndarray, bytes]:
    repaired = proposal.copy()
    current = repaired[mask].astype(np.int16)
    target = source[mask].astype(np.int16)
    values = np.rint((current * (4 - numerator) + target * numerator) / 4).astype(np.uint8)
    repaired[mask] = values
    delta = (values.astype(np.int16) - current).astype(">i2").tobytes()
    packet = struct.pack(">4sBI", b"ROV1", numerator, values.shape[0]) + zlib.compress(delta, 9)
    return repaired, packet


def _failures(result: Any) -> tuple[RepairFailure, ...]:
    values = getattr(result, "failures", ())
    return tuple(value for value in values if isinstance(value, RepairFailure))


def repair_until_verified(
    source: np.ndarray,
    proposal: np.ndarray,
    verifier: RepairVerifier,
    fallback: SharedLosslessCodec,
    *,
    halo_um: float = 2.0,
    mpp: float = 0.25,
) -> RepairResult:
    original = np.asarray(source)
    decoded = np.asarray(proposal)
    if original.dtype != np.uint8 or original.ndim != 3 or original.shape[2] != 3:
        raise ValueError("source must be uint8 RGB")
    if decoded.dtype != np.uint8 or decoded.shape != original.shape:
        raise ValueError("proposal must match the uint8 RGB source shape")

    initial = verifier.verify(original, decoded)
    if bool(getattr(initial, "passed", initial)):
        return RepairResult("verified", "proposal", decoded.copy(), ByteBreakdown())

    failures = _failures(initial)
    encoded_fallback = fallback.encode(original)
    fallback_decoded = fallback.decode(encoded_fallback.payload, original.shape)
    fallback_breakdown = ByteBreakdown(
        payload=encoded_fallback.breakdown.payload, fallback_signaling=1
    )
    fallback_result = RepairResult(
        "fallback", "whole_tile_lossless", fallback_decoded, fallback_breakdown
    )
    if not failures:
        return fallback_result

    mask = build_union_repair_mask(failures, halo_um=halo_um, mpp=mpp)
    attempted_overlay_bytes = 0
    for stage, numerator in (("finer_local_quantization", 2), ("transform_coefficient_overlay", 3)):
        repaired, packet = _blend_overlay(decoded, original, mask.pixels, numerator)
        attempted_overlay_bytes += len(packet)
        verification = verifier.verify(original, repaired)
        if bool(getattr(verification, "passed", verification)):
            stored = encode_repair_packet(mask, repaired)
            breakdown = ByteBreakdown(repair=len(stored))
            if breakdown.complete >= fallback_breakdown.complete:
                return fallback_result
            return RepairResult(
                "verified_repair",
                stage,
                repaired,
                breakdown,
                stored,
                mask_bytes=len(mask.encoded),
                residual_bytes=len(stored) - len(mask.encoded),
            )

    residual = encode_exact_residual(original, mask)
    repaired = apply_exact_residual(decoded, mask, residual)
    verification = verifier.verify(original, repaired)
    if bool(getattr(verification, "passed", verification)):
        stored = encode_repair_packet(mask, repaired)
        breakdown = ByteBreakdown(repair=len(stored))
        if breakdown.complete < fallback_breakdown.complete:
            return RepairResult(
                "verified_repair",
                "exact_pixel_residual",
                repaired,
                breakdown,
                stored,
                mask_bytes=len(mask.encoded),
                residual_bytes=len(stored) - len(mask.encoded),
            )
    return fallback_result
