from __future__ import annotations

import numpy as np


_HE_MATRIX = np.array(
    [[0.650, 0.072], [0.704, 0.990], [0.286, 0.105]], dtype=np.float64
)
_HE_INVERSE = np.linalg.pinv(_HE_MATRIX)


def optical_density(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb, dtype=np.float64)
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("optical density input must be RGB")
    bounded = np.clip(pixels, 0.0, 255.0)
    return np.clip(-np.log((bounded + 1.0) / 256.0), 0.0, 6.0)


def he_concentrations(rgb: np.ndarray) -> np.ndarray:
    density = optical_density(rgb)
    concentrations = density @ _HE_INVERSE.T
    return np.maximum(concentrations, 0.0)
