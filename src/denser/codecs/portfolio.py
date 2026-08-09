from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.core.models import ByteBreakdown, MethodResult


@dataclass(frozen=True, slots=True)
class CandidateTrial:
    encoded: EncodedCandidate
    decoded: np.ndarray


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    certificate_bytes: int
    reference_evidence_bytes: int

    def __post_init__(self) -> None:
        if self.certificate_bytes < 0 or self.reference_evidence_bytes < 0:
            raise ValueError("verification byte counts cannot be negative")

    @property
    def overhead(self) -> int:
        return self.certificate_bytes + self.reference_evidence_bytes


class CandidateVerifier(Protocol):
    policy_id: str

    def verify(self, source: np.ndarray, decoded: np.ndarray) -> VerificationResult: ...


def _with_verification(
    breakdown: ByteBreakdown,
    verification: VerificationResult,
    *,
    fallback: bool = False,
) -> ByteBreakdown:
    values = {
        name: getattr(breakdown, name) for name in ByteBreakdown.__dataclass_fields__
    }
    values["certificate"] += verification.certificate_bytes
    values["reference_evidence"] += verification.reference_evidence_bytes
    if fallback:
        values["fallback_signaling"] += 1
    return ByteBreakdown(**values)


def select_standard_portfolio(
    rgb: np.ndarray,
    candidates: list[CandidateTrial],
    verifier: CandidateVerifier,
    fallback: SharedLosslessCodec,
) -> MethodResult:
    source = np.asarray(rgb)
    verified: list[tuple[int, str, MethodResult]] = []
    for trial in candidates:
        if trial.decoded.shape != source.shape or trial.decoded.dtype != np.uint8:
            continue
        verification = verifier.verify(source, trial.decoded)
        if not verification.passed:
            continue
        breakdown = _with_verification(trial.encoded.breakdown, verification)
        result = MethodResult(
            method_id="standard-portfolio",
            profile_id=trial.encoded.profile_id,
            status="verified",
            breakdown=breakdown,
            verification_overhead=verification.overhead,
        )
        verified.append((result.complete_bytes, result.profile_id, result))
    if verified:
        return min(verified, key=lambda item: (item[0], item[1]))[2]

    encoded_fallback = fallback.encode(source)
    decoded_fallback = fallback.decode(encoded_fallback.payload, source.shape)
    verification = verifier.verify(source, decoded_fallback)
    if not verification.passed:
        raise RuntimeError("shared pixel-exact fallback failed the common verifier")
    breakdown = _with_verification(
        encoded_fallback.breakdown, verification, fallback=True
    )
    return MethodResult(
        method_id="standard-portfolio",
        profile_id=encoded_fallback.profile_id,
        status="fallback",
        breakdown=breakdown,
        verification_overhead=verification.overhead,
    )
