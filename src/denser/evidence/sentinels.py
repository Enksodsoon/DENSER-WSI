from __future__ import annotations

import numpy as np

from denser.evidence.nuclei import connected_component_stats
from denser.evidence.stain import sentinel_mask
from denser.evidence.types import PhysicalGrid


def sentinel_features(
    rgb: np.ndarray,
    grid: PhysicalGrid | None = None,
    *,
    hematoxylin: np.ndarray | None = None,
) -> tuple[float, ...]:
    selected_grid = grid or PhysicalGrid(0.25, 0.25)
    pixel_area_um2 = selected_grid.mpp_x * selected_grid.mpp_y
    minimum_pixels = max(1, int(np.ceil(0.05 / pixel_area_um2)))
    maximum_pixels = max(minimum_pixels, int(np.floor(4.0 / pixel_area_um2)))
    mask = sentinel_mask(
        np.asarray(rgb, dtype=np.uint8), hematoxylin=hematoxylin
    )
    components = [
        component
        for component in connected_component_stats(mask)
        if minimum_pixels <= component.size <= maximum_pixels
    ]
    total = sum(component.size for component in components)
    height, width = mask.shape
    if components:
        centroid_y = sum(component.sum_y for component in components) / total
        centroid_x = sum(component.sum_x for component in components) / total
    else:
        centroid_y = centroid_x = 0.0
    return (
        float(len(components)) * 1_000_000.0 / (mask.size * pixel_area_um2),
        total / mask.size,
        centroid_y / max(height - 1, 1),
        centroid_x / max(width - 1, 1),
    )
