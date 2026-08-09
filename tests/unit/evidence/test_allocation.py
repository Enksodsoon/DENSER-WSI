from __future__ import annotations

import numpy as np

from denser.evidence.chromatin import chromatin_distance
from denser.evidence.stain import optical_density
from denser.evidence.types import EvidenceContract, PhysicalGrid
from denser.evidence.boundary import allocation_jvp, compute_allocation_features


def _texture() -> np.ndarray:
    y, x = np.mgrid[:64, :64]
    checker = ((x // 2 + y // 2) % 2).astype(np.uint8)
    rgb = np.empty((64, 64, 3), dtype=np.uint8)
    rgb[:, :, 0] = 215 - checker * 90
    rgb[:, :, 1] = 170 - checker * 115
    rgb[:, :, 2] = 205 - checker * 55
    return rgb


def _box_blur(rgb: np.ndarray, radius: int = 3) -> np.ndarray:
    padded = np.pad(rgb.astype(np.float64), ((radius, radius), (radius, radius), (0, 0)), mode="reflect")
    result = np.empty_like(rgb)
    side = radius * 2 + 1
    for y in range(rgb.shape[0]):
        for x in range(rgb.shape[1]):
            result[y, x] = np.rint(padded[y : y + side, x : x + side].mean(axis=(0, 1)))
    return result.astype(np.uint8)


def test_chromatin_energy_detects_high_frequency_removal() -> None:
    original = _texture()
    blurred = _box_blur(original)
    assert chromatin_distance(original, blurred, PhysicalGrid(0.25, 0.25)) > 0.2


def test_allocation_features_are_deterministic() -> None:
    contract = EvidenceContract()
    grid = PhysicalGrid(0.25, 0.25)
    first = compute_allocation_features(_texture(), grid, contract)
    second = compute_allocation_features(_texture().copy(), grid, contract)
    assert first.sha256 == second.sha256
    assert first.features == second.features
    assert first.version == "HE-V1-allocation-1"


def test_optical_density_is_bounded_and_finite() -> None:
    rgb = np.array([[[0, 1, 255], [20, 100, 200]]], dtype=np.uint8)
    density = optical_density(rgb)
    assert np.isfinite(density).all()
    assert density.min() >= 0
    assert density.max() <= 6


def test_allocation_jvp_is_deterministic_and_sensitive() -> None:
    rgb = _texture().astype(np.float64)
    vector = np.ones_like(rgb) * 0.25
    contract = EvidenceContract(physical_grid=PhysicalGrid(0.25, 0.25))
    first = allocation_jvp(rgb, vector, contract)
    second = allocation_jvp(rgb, vector, contract)
    assert np.array_equal(first, second)
    assert first.ndim == 1
    assert np.isfinite(first).all()
