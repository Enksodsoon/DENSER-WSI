from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.core.models import ByteBreakdown
from denser.repair.mask import RepairFailure, build_union_repair_mask
from denser.repair.packet_v2 import (
    encode_composite_repair_packet,
    encode_repair_packet,
)
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


def _verify_changed(
    verifier: RepairVerifier,
    source: np.ndarray,
    proposal: np.ndarray,
    repaired: np.ndarray,
    initial: Any,
) -> Any:
    incremental = getattr(verifier, "verify_changed", None)
    if callable(incremental):
        changed = np.any(np.asarray(repaired) != np.asarray(proposal), axis=2)
        return incremental(source, repaired, initial, changed)
    return verifier.verify(source, repaired)


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

    def byte_dominated(payload_length: int) -> bool:
        return payload_length >= fallback_breakdown.complete or (
            maximum_repair_bytes is not None
            and payload_length > maximum_repair_bytes
        )

    prefix_parts: tuple[bytes, ...] = ()
    prefix_mask_bytes = 0
    prefix_residual_bytes = 0
    critical_groups = {"architecture", "rare_event_sentinels"}
    critical_failures = tuple(
        failure
        for failure in failures
        if critical_groups.intersection(failure.failed_groups)
    )
    if critical_failures:
        critical_mask = build_union_repair_mask(
            critical_failures, halo_um=halo_um, mpp=mpp
        )
        critical_residual = encode_exact_residual(original, critical_mask)
        critical_repaired = apply_exact_residual(
            decoded, critical_mask, critical_residual
        )
        critical_payload = encode_repair_packet(
            critical_mask, critical_repaired, base=decoded
        )
        if byte_dominated(len(critical_payload)):
            return fallback_result
        critical_verification = _verify_changed(
            verifier, original, decoded, critical_repaired, initial
        )
        if bool(getattr(critical_verification, "passed", critical_verification)):
            return RepairResult(
                "verified_repair",
                "critical_exact_residual",
                critical_repaired,
                ByteBreakdown(repair=len(critical_payload)),
                critical_payload,
                mask_bytes=len(critical_mask.encoded),
                residual_bytes=len(critical_payload) - len(critical_mask.encoded),
            )
        decoded = critical_repaired
        initial = critical_verification
        failures = _failures(initial)
        if not failures:
            return fallback_result
        prefix_parts = (critical_payload,)
        prefix_mask_bytes = len(critical_mask.encoded)
        prefix_residual_bytes = len(critical_payload) - len(critical_mask.encoded)

    mask = build_union_repair_mask(failures, halo_um=halo_um, mpp=mpp)

    def with_prefix(part: bytes) -> bytes:
        return (
            encode_composite_repair_packet((*prefix_parts, part))
            if prefix_parts
            else part
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
        overlay = encode_transform_overlay(
            original,
            decoded,
            mask,
            coefficients_per_block=count,
            quantization_step=step,
            block_size=evidence_cell_size,
        )
        stored = with_prefix(overlay)
        if byte_dominated(len(stored)):
            break
        repaired = apply_transform_overlay(decoded, overlay)
        verification = _verify_changed(verifier, original, decoded, repaired, initial)
        if bool(getattr(verification, "passed", verification)):
            breakdown = ByteBreakdown(repair=len(stored))
            accepted_overlay = RepairResult(
                "verified_repair",
                stage,
                repaired,
                breakdown,
                stored,
                mask_bytes=prefix_mask_bytes + len(mask.encoded),
                residual_bytes=prefix_residual_bytes,
                overlay_bytes=len(overlay),
            )
            break

    residual = encode_exact_residual(original, mask)
    repaired = apply_exact_residual(decoded, mask, residual)
    exact = encode_repair_packet(mask, repaired, base=decoded)
    stored = with_prefix(exact)
    if (
        not byte_dominated(len(stored))
        and (accepted_overlay is None or len(stored) < len(accepted_overlay.payload))
    ):
        verification = _verify_changed(verifier, original, decoded, repaired, initial)
    else:
        verification = False
    if bool(getattr(verification, "passed", verification)):
        breakdown = ByteBreakdown(repair=len(stored))
        return RepairResult(
            "verified_repair",
            (
                "critical_exact_then_exact_pixel_residual"
                if prefix_parts
                else "exact_pixel_residual"
            ),
            repaired,
            breakdown,
            stored,
            mask_bytes=prefix_mask_bytes + len(mask.encoded),
            residual_bytes=(
                prefix_residual_bytes + len(exact) - len(mask.encoded)
            ),
        )
    if accepted_overlay is not None and prefix_parts:
        return RepairResult(
            accepted_overlay.status,
            f"critical_exact_then_{accepted_overlay.stage}",
            accepted_overlay.decoded,
            accepted_overlay.breakdown,
            accepted_overlay.payload,
            accepted_overlay.mask_bytes,
            accepted_overlay.overlay_bytes,
            accepted_overlay.residual_bytes,
        )
    return accepted_overlay or fallback_result
