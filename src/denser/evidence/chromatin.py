from __future__ import annotations

import numpy as np

from denser.evidence.stain import he_concentrations
from denser.evidence.types import EvidenceContract, PhysicalGrid


def chromatin_band_energy(
    rgb: np.ndarray, grid: PhysicalGrid, contract: EvidenceContract | None = None
) -> tuple[float, ...]:
    selected_contract = contract or EvidenceContract(physical_grid=grid)
    hematoxylin = he_concentrations(rgb)[:, :, 0]
    centered = hematoxylin - hematoxylin.mean()
    spectrum = np.abs(np.fft.rfft2(centered)) ** 2
    fy = np.fft.fftfreq(centered.shape[0], d=grid.mpp_y)
    fx = np.fft.rfftfreq(centered.shape[1], d=grid.mpp_x)
    radius = np.sqrt(fy[:, None] ** 2 + fx[None, :] ** 2)
    total = float(spectrum.sum())
    if total <= 1e-20:
        return tuple(0.0 for _ in selected_contract.chromatin_bands_cycles_um)
    energies = []
    for low, high in selected_contract.chromatin_bands_cycles_um:
        mask = (radius >= low) & (radius < high)
        energies.append(round(float(spectrum[mask].sum() / total), 12))
    return tuple(energies)


def chromatin_distance(
    original: np.ndarray, decoded: np.ndarray, grid: PhysicalGrid
) -> float:
    first = np.asarray(chromatin_band_energy(original, grid), dtype=np.float64)
    second = np.asarray(chromatin_band_energy(decoded, grid), dtype=np.float64)
    denominator = max(float(np.abs(first).sum()), 1e-12)
    return float(np.abs(first - second).sum() / denominator)
