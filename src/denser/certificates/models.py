from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from denser.core.canonical import canonical_json_bytes
from denser.evidence.types import AcceptanceEvidence


@dataclass(frozen=True, slots=True)
class ReferenceEvidencePayload:
    version: str
    quantization: float
    max_absolute_error: float
    groups: tuple[tuple[str, tuple[int, ...]], ...]

    def __post_init__(self) -> None:
        if self.quantization <= 0 or not math.isfinite(self.quantization):
            raise ValueError("reference quantization must be finite and positive")
        if self.max_absolute_error != self.quantization / 2:
            raise ValueError("reference error bound must equal half the quantization step")
        if not self.groups:
            raise ValueError("reference evidence groups must not be empty")

    def document(self) -> dict[str, object]:
        return {
            "version": self.version,
            "quantization": self.quantization,
            "max_absolute_error": self.max_absolute_error,
            "groups": [
                {"name": name, "values": list(values)} for name, values in self.groups
            ],
        }

    @property
    def encoded_bytes(self) -> int:
        return len(canonical_json_bytes(self.document()))

def build_reference_payload(
    source_evidence: AcceptanceEvidence, quantization: float
) -> ReferenceEvidencePayload:
    if quantization <= 0 or not math.isfinite(quantization):
        raise ValueError("quantization must be finite and positive")
    groups = tuple(
        (name, tuple(int(round(float(value) / quantization)) for value in values))
        for name, values in source_evidence.groups
    )
    return ReferenceEvidencePayload(
        version=source_evidence.version,
        quantization=float(quantization),
        max_absolute_error=float(quantization) / 2,
        groups=groups,
    )


@dataclass(frozen=True, slots=True)
class EvidenceCertificate:
    version: str
    mode: str
    self_verifying: bool
    contract_digest: str
    implementation_digest: str
    mpp_x: float
    mpp_y: float
    reference_payload: ReferenceEvidencePayload | None
    candidate_id: str
    fallback_id: str
    repair_region_hex: str
    decoded_evidence_sha256: str
    packet_sha256: str
    decoded_rgb_sha256: str
    verification_status: str
    certificate_digest: str

    def document(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "version": self.version,
            "mode": self.mode,
            "self_verifying": self.self_verifying,
            "contract_digest": self.contract_digest,
            "implementation_digest": self.implementation_digest,
            "physical_scale": {"mpp_x": self.mpp_x, "mpp_y": self.mpp_y},
            "reference_payload": None if self.reference_payload is None else self.reference_payload.document(),
            "candidate_id": self.candidate_id,
            "fallback_id": self.fallback_id,
            "repair_region_hex": self.repair_region_hex,
            "decoded_evidence_sha256": self.decoded_evidence_sha256,
            "packet_sha256": self.packet_sha256,
            "decoded_rgb_sha256": self.decoded_rgb_sha256,
            "verification_status": self.verification_status,
        }
        if include_digest:
            value["certificate_digest"] = self.certificate_digest
        return value

    def expected_digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.document(include_digest=False))).hexdigest()

    @property
    def encoded_bytes(self) -> int:
        return len(canonical_json_bytes(self.document()))
