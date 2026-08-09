from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from denser.core.canonical import canonical_json_bytes
from denser.evidence.types import AuditEvidence


@dataclass(frozen=True, slots=True)
class AuditProfile:
    version: str = "AUDIT-V1-withheld-1"
    histogram_bins: int = 32


def compute_audit_evidence(rgb: np.ndarray, audit_profile: AuditProfile) -> AuditEvidence:
    pixels = np.asarray(rgb, dtype=np.uint8).astype(np.float64)
    luminance = pixels.mean(axis=2)
    laplacian = (
        -4 * luminance
        + np.roll(luminance, 1, 0)
        + np.roll(luminance, -1, 0)
        + np.roll(luminance, 1, 1)
        + np.roll(luminance, -1, 1)
    )
    histogram, _ = np.histogram(
        luminance, bins=audit_profile.histogram_bins, range=(0, 256)
    )
    features = [("laplacian.energy", round(float(np.mean(laplacian**2)), 12))]
    features.extend(
        (f"luminance.bin.{index}", round(float(value / luminance.size), 12))
        for index, value in enumerate(histogram)
    )
    canonical = tuple(features)
    digest = hashlib.sha256(
        canonical_json_bytes({"version": audit_profile.version, "features": canonical})
    ).hexdigest()
    return AuditEvidence(audit_profile.version, canonical, digest)
