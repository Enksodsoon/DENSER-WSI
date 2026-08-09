from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from denser.certificates.encode import build_certificate
from denser.certificates.verify import verify_certificate
from denser.evidence.types import AcceptanceContract
from denser.method.candidates import CandidateProfile, build_uniform_candidates, decode_candidate


def fixture() -> tuple[np.ndarray, object, AcceptanceContract]:
    rng = np.random.default_rng(17)
    source = rng.integers(0, 256, size=(16, 16, 3), dtype=np.uint8)
    contract = AcceptanceContract(
        nuclear_relative_tolerance=1.0,
        architecture_relative_tolerance=1.0,
        sentinel_relative_tolerance=1.0,
        visual_relative_tolerance=1.0,
    )
    candidate = build_uniform_candidates(source, CandidateProfile((1.0,)))[0]
    return decode_candidate(candidate.payload), build_certificate(source, candidate, contract), contract


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_digest", "0" * 64),
        ("packet_sha256", "f" * 64),
        ("certificate_digest", "1" * 64),
    ],
)
def test_tampered_certificate_fails_closed(field: str, value: str) -> None:
    decoded, certificate, contract = fixture()
    tampered = replace(certificate, **{field: value})
    result = verify_certificate(decoded, tampered, contract)
    assert not result.passed
    assert result.failure_reason.startswith("integrity:") or result.failure_reason == "contract_digest_mismatch"


def test_tampered_reference_payload_fails_closed() -> None:
    decoded, certificate, contract = fixture()
    payload = replace(certificate.reference_payload, groups=(("visual", (0,)),))
    tampered = replace(certificate, reference_payload=payload)
    assert not verify_certificate(decoded, tampered, contract).passed
