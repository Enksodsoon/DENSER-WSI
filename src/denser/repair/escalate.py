from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.core.models import ByteBreakdown
from denser.repair.mask import RepairFailure, build_union_repair_mask
from denser.repair.packet_v2 import encode_repair_packet
from denser.repair.residual import apply_exact_residual, encode_exact_residual
from denser.repair.transform_overlay import (
    apply_transform_overlay,
    encode_transform_overlay,
)


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
    initial_verification: Any | None = None,
    encoded_fallback: EncodedCandidate | None = None,
    fallback_decoded: np.ndarray | None = None,
    maximum_repair_bytes: int | None = None,
) -> RepairResult:
    original = np.asarray(source)
    decoded = np.asarray(proposal)
    if original.dtype != np.uint8 or original.ndim != 3 or original.shape[2] != 3:
        raise ValueError("source must be uint8 RGB")
    if decoded.dtype != np.uint8 or decoded.shape != original.shape:
        raise ValueError("proposal must match the uint8 RGB source shape")

    if maximum_repair_bytes is not None and maximum_repair_bytes < 0:
        raise ValueError("maximum repair bytes cannot be negative")
    initial = (
        initial_verification
        if initial_verification is not None
        else verifier.verify(original, decoded)
    )
    if bool(getattr(initial, "passed", initial)):
        return RepairResult("verified", "proposal", decoded.copy(), ByteBreakdown())

    failures = _failures(initial)
    selected_fallback = encoded_fallback or fallback.encode(original)
    selected_fallback_decoded = (
        np.asarray(fallback_decoded)
        if fallback_decoded is not None
        else fallback.decode(selected_fallback.payload, original.shape)
    )
    if selected_fallback.codec_id != fallback.codec_id or not np.array_equal(
        selected_fallback_decoded, original
    ):
        raise ValueError("provided fallback is not the exact source tile")
    fallback_breakdown = ByteBreakdown(
        payload=selected_fallback.breakdown.payload, fallback_signaling=1
    )
    fallback_result = RepairResult(
        "fallback", "whole_tile_lossless", selected_fallback_decoded, fallback_breakdown
    )
    if not failures:
        return fallback_result

    mask = build_union_repair_mask(failures, halo_um=halo_um, mpp=mpp)
    def byte_dominated(payload_length: int) -> bool:
        return payload_length >= fallback_breakdown.complete or (
            maximum_repair_bytes is not None
            and payload_length > maximum_repair_bytes
        )

    accepted_overlay: RepairResult | None = None
    evidence_cell_size = max(8, min(128, round(8.0 / mpp)))
    failed_groups = {
        name for failure in failures for name in failure.failed_groups
    }
    stages = []
    if not failed_groups or failed_groups <= {"visual"}:
        stages.append(("finer_local_quantization", 0, 1.0))
    if not failed_groups or failed_groups <= {"visual", "nuclear_objects"}:
        stages.append(("transform_coefficient_overlay", 16, 1.0))
    for stage, count, step in stages:
        stored = encode_transform_overlay(
            original,
            decoded,
            mask,
            coefficients_per_block=count,
            quantization_step=step,
            block_size=evidence_cell_size,
        )
        if byte_dominated(len(stored)):
            break
        repaired = apply_transform_overlay(decoded, stored)
        verification = verifier.verify(original, repaired)
        if bool(getattr(verification, "passed", verification)):
            breakdown = ByteBreakdown(repair=len(stored))
            accepted_overlay = RepairResult(
                "verified_repair",
                stage,
                repaired,
                breakdown,
                stored,
                mask_bytes=len(mask.encoded),
                residual_bytes=len(stored) - len(mask.encoded),
            )
            break

    residual = encode_exact_residual(original, mask)
    repaired = apply_exact_residual(decoded, mask, residual)
    stored = encode_repair_packet(mask, repaired)
    if (
        not byte_dominated(len(stored))
        and (accepted_overlay is None or len(stored) < len(accepted_overlay.payload))
    ):
        verification = verifier.verify(original, repaired)
    else:
        verification = False
    if bool(getattr(verification, "passed", verification)):
        breakdown = ByteBreakdown(repair=len(stored))
        return RepairResult(
            "verified_repair",
            "exact_pixel_residual",
            repaired,
            breakdown,
            stored,
            mask_bytes=len(mask.encoded),
            residual_bytes=len(stored) - len(mask.encoded),
        )
    return accepted_overlay or fallback_result
