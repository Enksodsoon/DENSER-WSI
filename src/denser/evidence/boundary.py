from __future__ import annotations

import hashlib
import math

import numpy as np

from denser.core.canonical import canonical_json_bytes
from denser.evidence.chromatin import chromatin_band_energy
from denser.evidence.stain import he_concentrations
from denser.evidence.types import AllocationEvidence, EvidenceContract, PhysicalGrid


def _blur_axis(values: np.ndarray, radius: int, axis: int) -> np.ndarray:
    if radius <= 0:
        return values
    kernel = np.full(radius * 2 + 1, 1.0 / (radius * 2 + 1))
    return np.apply_along_axis(
        lambda line: np.convolve(np.pad(line, radius, mode="reflect"), kernel, mode="valid"),
        axis,
        values,
    )


def _box_blur(values: np.ndarray, radius: int) -> np.ndarray:
    return _blur_axis(_blur_axis(values, radius, 0), radius, 1)


def _feature_items(
    rgb: np.ndarray, grid: PhysicalGrid, contract: EvidenceContract
) -> tuple[tuple[str, float], ...]:
    concentrations = he_concentrations(rgb)
    features: list[tuple[str, float]] = []
    for index, stain in enumerate(("hematoxylin", "eosin")):
        features.append((f"stain.{stain}.mean", round(float(concentrations[:, :, index].mean()), 12)))
        features.append((f"stain.{stain}.std", round(float(concentrations[:, :, index].std()), 12)))
    hematoxylin = concentrations[:, :, 0]
    for scale_um in contract.boundary_scales_um:
        radius = max(1, int(round(scale_um / grid.mean_mpp / 2)))
        smooth = _box_blur(hematoxylin, radius)
        gradient_y, gradient_x = np.gradient(smooth)
        for orientation in contract.orientations_deg:
            angle = math.radians(orientation)
            response = np.abs(math.cos(angle) * gradient_x + math.sin(angle) * gradient_y)
            features.append(
                (
                    f"boundary.{scale_um:g}um.{orientation:g}deg",
                    round(float(response.mean()), 12),
                )
            )
    for index, energy in enumerate(chromatin_band_energy(rgb, grid, contract)):
        features.append((f"chromatin.band.{index}", energy))
    return tuple(features)


def compute_allocation_features(
    rgb: np.ndarray, physical_grid: PhysicalGrid, contract: EvidenceContract
) -> AllocationEvidence:
    features = _feature_items(rgb, physical_grid, contract)
    document = {
        "version": contract.version,
        "mpp_x": physical_grid.mpp_x,
        "mpp_y": physical_grid.mpp_y,
        "features": list(features),
    }
    digest = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    return AllocationEvidence(contract.version, features, digest)


def allocation_jvp(
    rgb: np.ndarray, vector: np.ndarray, contract: EvidenceContract
) -> np.ndarray:
    pixels = np.asarray(rgb, dtype=np.float64)
    direction = np.asarray(vector, dtype=np.float64)
    if pixels.shape != direction.shape or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("JVP input and vector must have matching RGB shapes")
    epsilon = 1e-3
    plus = compute_allocation_features(
        np.clip(pixels + epsilon * direction, 0, 255), contract.physical_grid, contract
    )
    minus = compute_allocation_features(
        np.clip(pixels - epsilon * direction, 0, 255), contract.physical_grid, contract
    )
    return (
        np.asarray(plus.vector(), dtype=np.float64)
        - np.asarray(minus.vector(), dtype=np.float64)
    ) / (2 * epsilon)
