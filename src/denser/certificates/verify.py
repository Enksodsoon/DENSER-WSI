from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from denser.certificates.encode import contract_digest
from denser.certificates.models import EvidenceCertificate
from denser.evidence.architecture import compute_acceptance_evidence
from denser.evidence.types import AcceptanceContract, PhysicalGrid


@dataclass(frozen=True, slots=True)
class CertificateVerificationResult:
    passed: bool
    original_pixels_required: bool
    failure_reason: str = ""


def verify_certificate(
    decoded_rgb: np.ndarray,
    certificate: EvidenceCertificate,
    contract: AcceptanceContract,
) -> CertificateVerificationResult:
    if certificate.certificate_digest != certificate.expected_digest():
        return CertificateVerificationResult(False, False, "integrity:certificate_digest")
    if certificate.contract_digest != contract_digest(contract):
        return CertificateVerificationResult(False, False, "contract_digest_mismatch")
    decoded = np.asarray(decoded_rgb)
    if decoded.dtype != np.uint8 or decoded.ndim != 3 or decoded.shape[2] != 3:
        return CertificateVerificationResult(False, False, "integrity:decoded_shape")
    decoded_digest = hashlib.sha256(decoded.tobytes(order="C")).hexdigest()
    if decoded_digest != certificate.decoded_rgb_sha256:
        return CertificateVerificationResult(False, False, "integrity:decoded_rgb_digest")
    if certificate.mode != "self_verifying" or not certificate.self_verifying:
        return CertificateVerificationResult(False, True, "reference_pixels_required")
    reference = certificate.reference_payload
    if reference is None:
        return CertificateVerificationResult(False, False, "integrity:reference_payload_missing")

    try:
        grid = PhysicalGrid(certificate.mpp_x, certificate.mpp_y)
        candidate = compute_acceptance_evidence(decoded, grid, contract)
        candidate_groups = dict(candidate.groups)
        tolerance = {
            "nuclear_objects": contract.nuclear_relative_tolerance,
            "architecture": contract.architecture_relative_tolerance,
            "rare_event_sentinels": contract.sentinel_relative_tolerance,
            "visual": contract.visual_relative_tolerance,
        }
        if set(candidate_groups) != {name for name, _values in reference.groups}:
            return CertificateVerificationResult(False, False, "integrity:reference_groups")
        for name, quantized in reference.groups:
            observed = candidate_groups[name]
            if len(observed) != len(quantized):
                return CertificateVerificationResult(False, False, "integrity:reference_shape")
            for stored, value in zip(quantized, observed, strict=True):
                reconstructed = stored * reference.quantization
                allowed = (
                    tolerance[name] * max(abs(reconstructed), 1e-6)
                    + reference.max_absolute_error
                )
                if abs(float(value) - reconstructed) > allowed:
                    return CertificateVerificationResult(False, False, f"evidence:{name}")
    except (KeyError, TypeError, ValueError, OverflowError):
        return CertificateVerificationResult(False, False, "integrity:reference_payload")
    return CertificateVerificationResult(True, False)
