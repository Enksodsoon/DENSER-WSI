from __future__ import annotations

import numpy as np

from denser.evidence.types import PhysicalGrid


_HEMATOXYLIN = np.array((0.65, 0.70, 0.29), dtype=np.float64)
_EOSIN = np.array((0.07, 0.99, 0.11), dtype=np.float64)


def optical_density(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb, dtype=np.float64)
    if pixels.ndim != 3 or pixels.shape[2] != 3 or not np.isfinite(pixels).all():
        raise ValueError("optical density requires finite RGB pixels")
    return np.clip(-np.log((np.clip(pixels, 0.0, 255.0) + 1.0) / 256.0), 0.0, 6.0)


def he_concentrations(rgb: np.ndarray) -> np.ndarray:
    density = optical_density(rgb)
    hematoxylin_projection = density @ _HEMATOXYLIN
    eosin_projection = density @ _EOSIN
    hematoxylin = np.maximum(hematoxylin_projection - 0.40 * eosin_projection, 0.0)
    eosin = np.maximum(eosin_projection - 0.10 * hematoxylin_projection, 0.0)
    return np.stack((hematoxylin, eosin), axis=2)


def hematoxylin_concentration(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("stain evidence requires canonical uint8 RGB pixels")
    return he_concentrations(pixels)[:, :, 0]


def boundary_spectrum(
    field: np.ndarray, grid: PhysicalGrid | None = None
) -> tuple[float, ...]:
    values = np.asarray(field, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("boundary spectrum requires a two-dimensional field")
    spectrum = []
    selected_grid = grid or PhysicalGrid(0.25, 0.25)
    for scale_um in (0.25, 0.50, 1.00):
        offset = max(1, int(round(scale_um / selected_grid.mean_mpp)))
        if min(values.shape) <= offset:
            spectrum.append(0.0)
            continue
        horizontal = np.abs(values[:, offset:] - values[:, :-offset]).mean()
        vertical = np.abs(values[offset:, :] - values[:-offset, :]).mean()
        spectrum.append(float((horizontal + vertical) / 2.0))
    return tuple(spectrum)


def chromatin_frequency(
    field: np.ndarray, grid: PhysicalGrid | None = None
) -> tuple[float, float]:
    values = np.asarray(field, dtype=np.float64)
    if min(values.shape) < 3:
        return (0.0, 0.0)
    selected_grid = grid or PhysicalGrid(0.25, 0.25)
    laplacian = np.abs(
        -4.0 * values[1:-1, 1:-1]
        + values[:-2, 1:-1]
        + values[2:, 1:-1]
        + values[1:-1, :-2]
        + values[1:-1, 2:]
    ) / (selected_grid.mean_mpp**2)
    return (float(laplacian.mean()), float(np.quantile(laplacian, 0.95)))


def sentinel_mask(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb, dtype=np.uint8)
    concentration = hematoxylin_concentration(pixels)
    intensity = pixels.astype(np.float64).mean(axis=2)
    return (concentration > 0.90) & (intensity < 105.0)
