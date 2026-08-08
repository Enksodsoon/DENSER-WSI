from __future__ import annotations

import hashlib
from dataclasses import replace

import numpy as np

from denser.certificates.models import (
    EvidenceCertificate,
    build_reference_payload,
)
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.core.canonical import canonical_json_bytes
from denser.evidence.architecture import compute_acceptance_evidence
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.method.candidates import decode_candidate


_IMPLEMENTATION_ID = b"denser-he-v1-certificate-implementation-1"


def _contract_document(contract: AcceptanceContract) -> dict[str, object]:
    return {
        "version": contract.version,
        "nuclear_relative_tolerance": contract.nuclear_relative_tolerance,
        "architecture_relative_tolerance": contract.architecture_relative_tolerance,
        "sentinel_relative_tolerance": contract.sentinel_relative_tolerance,
        "visual_relative_tolerance": contract.visual_relative_tolerance,
    }


def contract_digest(contract: AcceptanceContract) -> str:
    return hashlib.sha256(canonical_json_bytes(_contract_document(contract))).hexdigest()


def _base_certificate(
    source_rgb: np.ndarray,
    candidate: EncodedCandidate,
    contract: AcceptanceContract,
    *,
    mode: str,
    quantization: float,
    grid: PhysicalGrid,
) -> EvidenceCertificate:
    source = np.asarray(source_rgb)
    if candidate.codec_id == SharedLosslessCodec.codec_id:
        decoded = SharedLosslessCodec().decode(candidate.payload, source.shape)
    else:
        decoded = decode_candidate(candidate.payload)
    if source.dtype != np.uint8 or source.shape != decoded.shape:
        raise ValueError("source and decoded candidate must be matching uint8 RGB arrays")
    reference = compute_acceptance_evidence(source, grid, contract)
    decoded_evidence = compute_acceptance_evidence(decoded, grid, contract)
    payload = build_reference_payload(reference, quantization) if mode == "self_verifying" else None
    unsigned = EvidenceCertificate(
        version="HE-V1-certificate-1",
        mode=mode,
        self_verifying=mode == "self_verifying",
        contract_digest=contract_digest(contract),
        implementation_digest=hashlib.sha256(_IMPLEMENTATION_ID).hexdigest(),
        mpp_x=grid.mpp_x,
        mpp_y=grid.mpp_y,
        reference_payload=payload,
        candidate_id=f"{candidate.codec_id}:{candidate.profile_id}",
        fallback_id=SharedLosslessCodec.profile_id,
        repair_region_hex="",
        decoded_evidence_sha256=decoded_evidence.sha256,
        packet_sha256=hashlib.sha256(candidate.payload).hexdigest(),
        decoded_rgb_sha256=hashlib.sha256(decoded.tobytes(order="C")).hexdigest(),
        verification_status="encoder_verified",
        certificate_digest="",
    )
    return replace(unsigned, certificate_digest=unsigned.expected_digest())


def build_certificate(
    source_rgb: np.ndarray,
    accepted_candidate: EncodedCandidate,
    contract: AcceptanceContract,
    *,
    quantization: float = 1e-6,
    physical_grid: PhysicalGrid | None = None,
) -> EvidenceCertificate:
    return _base_certificate(
        source_rgb,
        accepted_candidate,
        contract,
        mode="self_verifying",
        quantization=quantization,
        grid=physical_grid or PhysicalGrid(0.25, 0.25),
    )


def build_attested_digest_certificate(
    source_rgb: np.ndarray,
    accepted_candidate: EncodedCandidate,
    contract: AcceptanceContract,
    *,
    physical_grid: PhysicalGrid | None = None,
) -> EvidenceCertificate:
    return _base_certificate(
        source_rgb,
        accepted_candidate,
        contract,
        mode="attested_digest",
        quantization=1e-6,
        grid=physical_grid or PhysicalGrid(0.25, 0.25),
    )


def encode_certificate(certificate: EvidenceCertificate) -> bytes:
    return canonical_json_bytes(certificate.document())
