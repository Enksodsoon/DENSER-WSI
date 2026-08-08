from __future__ import annotations

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.portfolio import (
    CandidateTrial,
    VerificationResult,
    select_standard_portfolio,
)
from denser.core.models import ByteBreakdown


def _rgb() -> np.ndarray:
    return np.zeros((2, 2, 3), dtype=np.uint8)


def _candidate(profile: str, size: int, marker: int) -> CandidateTrial:
    encoded = EncodedCandidate("standard", profile, bytes([marker]) * size, ByteBreakdown(payload=size))
    return CandidateTrial(encoded, np.full((2, 2, 3), marker, dtype=np.uint8))


class _Verifier:
    policy_id = "HE-V1-self-verifying"

    def verify(self, source: np.ndarray, decoded: np.ndarray) -> VerificationResult:
        passed = np.array_equal(source, decoded) or int(decoded[0, 0, 0]) >= 2
        return VerificationResult(passed, certificate_bytes=11, reference_evidence_bytes=7)


def test_standard_portfolio_chooses_smallest_verified_candidate() -> None:
    candidates = [_candidate("q50", 100, 1), _candidate("q75", 140, 2), _candidate("q90", 180, 3)]
    result = select_standard_portfolio(_rgb(), candidates, _Verifier(), SharedLosslessCodec())
    assert result.profile_id == "q75"
    assert result.breakdown.complete == 140 + result.verification_overhead
    assert result.verification_overhead == 18


def test_standard_portfolio_uses_shared_fallback_when_all_fail() -> None:
    result = select_standard_portfolio(
        _rgb(), [_candidate("q50", 100, 1)], _Verifier(), SharedLosslessCodec()
    )
    assert result.status == "fallback"
    assert result.profile_id == SharedLosslessCodec.profile_id
    assert result.breakdown.fallback_signaling > 0


def test_selection_uses_complete_bytes_including_equal_safety_overhead() -> None:
    class VariableVerifier(_Verifier):
        def verify(self, source: np.ndarray, decoded: np.ndarray) -> VerificationResult:
            marker = int(decoded[0, 0, 0])
            return VerificationResult(True, certificate_bytes=marker * 50, reference_evidence_bytes=0)

    result = select_standard_portfolio(
        _rgb(), [_candidate("small-payload", 100, 3), _candidate("larger-payload", 120, 1)],
        VariableVerifier(), SharedLosslessCodec()
    )
    assert result.profile_id == "larger-payload"
