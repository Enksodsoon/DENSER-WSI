from __future__ import annotations

import json
import hashlib
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from denser.certificates.encode import (
    build_attested_digest_certificate,
    build_certificate,
    encode_certificate,
)
from denser.certificates.models import build_reference_payload
from denser.certificates.verify import (
    verify_certificate,
    verify_encoder_certificate_with_evidence,
)
from denser.evidence.architecture import compute_acceptance_evidence
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.method.candidates import CandidateProfile, build_uniform_candidates, decode_candidate


def source_rgb() -> np.ndarray:
    yy, xx = np.mgrid[:16, :16]
    return np.stack(((xx * 9) % 256, (yy * 11) % 256, ((xx + yy) * 7) % 256), axis=2).astype(np.uint8)


def accepted_candidate():
    return build_uniform_candidates(source_rgb(), CandidateProfile((1.0,)))[0]


def contract() -> AcceptanceContract:
    return AcceptanceContract(
        nuclear_relative_tolerance=0.5,
        architecture_relative_tolerance=0.5,
        sentinel_relative_tolerance=0.5,
        visual_relative_tolerance=0.5,
    )


def test_certificate_verifies_without_original_pixels() -> None:
    candidate = accepted_candidate()
    cert = build_certificate(source_rgb(), candidate, contract())
    decoded = decode_candidate(candidate.payload)
    result = verify_certificate(decoded, cert, contract())
    assert result.passed
    assert result.original_pixels_required is False
    assert len(encode_certificate(cert)) == cert.encoded_bytes


def test_reference_payload_has_explicit_bounded_error() -> None:
    evidence = compute_acceptance_evidence(source_rgb(), PhysicalGrid(0.25, 0.25), contract())
    payload = build_reference_payload(evidence, quantization=1e-4)
    assert payload.quantization == 1e-4
    assert payload.max_absolute_error == 5e-5
    assert payload.encoded_bytes > 0


def test_digest_only_certificate_is_not_marked_self_verifying() -> None:
    cert = build_attested_digest_certificate(source_rgb(), accepted_candidate(), contract())
    assert cert.mode == "attested_digest"
    assert cert.self_verifying is False


def test_self_verifying_certificate_matches_public_schema() -> None:
    certificate = build_certificate(source_rgb(), accepted_candidate(), contract())
    schema = json.loads(Path("schemas/evidence_certificate.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(certificate.document())


def test_certificate_binds_allocation_payload_and_repair_bytes() -> None:
    candidate = accepted_candidate()
    repair = b"repair-bytes"
    decoded = decode_candidate(candidate.payload, candidate.allocation_map)
    certificate = build_certificate(
        source_rgb(), candidate, contract(), decoded_rgb=decoded, repair_payload=repair
    )
    assert certificate.packet_sha256 == hashlib.sha256(
        candidate.allocation_map + candidate.payload + repair
    ).hexdigest()
    assert certificate.repair_region_hex == hashlib.sha256(repair).hexdigest()


def test_precomputed_evidence_produces_identical_certificate_and_verification() -> None:
    source = source_rgb()
    candidate = accepted_candidate()
    decoded = decode_candidate(candidate.payload, candidate.allocation_map)
    grid = PhysicalGrid(0.25, 0.25)
    reference = compute_acceptance_evidence(source, grid, contract())
    decoded_evidence = compute_acceptance_evidence(decoded, grid, contract())
    baseline = build_certificate(
        source, candidate, contract(), physical_grid=grid, decoded_rgb=decoded
    )
    reused = build_certificate(
        source,
        candidate,
        contract(),
        physical_grid=grid,
        decoded_rgb=decoded,
        reference_evidence=reference,
        decoded_evidence=decoded_evidence,
    )
    assert reused == baseline
    assert verify_certificate(decoded, reused, contract()).passed


def test_encoder_certificate_verification_reuses_bound_decoded_evidence(
    monkeypatch,
) -> None:
    source = source_rgb()
    candidate = accepted_candidate()
    decoded = decode_candidate(candidate.payload, candidate.allocation_map)
    grid = PhysicalGrid(0.25, 0.25)
    decoded_evidence = compute_acceptance_evidence(decoded, grid, contract())
    certificate = build_certificate(
        source,
        candidate,
        contract(),
        physical_grid=grid,
        decoded_rgb=decoded,
        decoded_evidence=decoded_evidence,
    )

    def unexpected(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("encoder verification must not re-extract bound evidence")

    monkeypatch.setattr(
        "denser.certificates.verify.compute_acceptance_evidence", unexpected
    )
    assert verify_encoder_certificate_with_evidence(
        decoded, certificate, contract(), decoded_evidence
    ).passed
