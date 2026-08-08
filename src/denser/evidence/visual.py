from __future__ import annotations

import numpy as np


def visual_features(rgb: np.ndarray) -> tuple[float, ...]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    features: list[float] = []
    for channel in range(3):
        histogram, _ = np.histogram(pixels[:, :, channel], bins=16, range=(0, 256))
        features.extend((histogram / pixels[:, :, channel].size).tolist())
    luminance = pixels.astype(np.float64).mean(axis=2)
    features.extend((float(luminance.mean() / 255), float(luminance.std() / 255)))
    return tuple(features)
