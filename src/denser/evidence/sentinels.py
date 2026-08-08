from __future__ import annotations

import numpy as np

from denser.evidence.nuclei import connected_components


def sentinel_features(rgb: np.ndarray) -> tuple[float, ...]:
    intensity = np.asarray(rgb, dtype=np.uint8).astype(np.float64).mean(axis=2)
    components = [
        component
        for component in connected_components(intensity < 80)
        if 1 <= len(component) <= 16
    ]
    total = sum(len(component) for component in components)
    return (float(len(components)), total / intensity.size)
