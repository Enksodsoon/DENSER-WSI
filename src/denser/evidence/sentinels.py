from __future__ import annotations

import numpy as np

from denser.evidence.nuclei import connected_components
from denser.evidence.stain import sentinel_mask
from denser.evidence.types import PhysicalGrid


def sentinel_features(
    rgb: np.ndarray, grid: PhysicalGrid | None = None
) -> tuple[float, ...]:
    selected_grid = grid or PhysicalGrid(0.25, 0.25)
    pixel_area_um2 = selected_grid.mpp_x * selected_grid.mpp_y
    minimum_pixels = max(1, int(np.ceil(0.05 / pixel_area_um2)))
    maximum_pixels = max(minimum_pixels, int(np.floor(4.0 / pixel_area_um2)))
    mask = sentinel_mask(np.asarray(rgb, dtype=np.uint8))
    components = [
        component
        for component in connected_components(mask)
        if minimum_pixels <= len(component) <= maximum_pixels
    ]
    total = sum(len(component) for component in components)
    height, width = mask.shape
    if components:
        centroid_y = sum(sum(y for y, _x in component) for component in components) / total
        centroid_x = sum(sum(x for _y, x in component) for component in components) / total
    else:
        centroid_y = centroid_x = 0.0
    return (
        float(len(components)) * 1_000_000.0 / (mask.size * pixel_area_um2),
        total / mask.size,
        centroid_y / max(height - 1, 1),
        centroid_x / max(width - 1, 1),
    )
