from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from denser.evidence.stain import (
    boundary_spectrum,
    chromatin_frequency,
    hematoxylin_concentration,
)
from denser.evidence.types import PhysicalGrid


@dataclass(frozen=True, slots=True)
class ComponentStats:
    size: int
    sum_y: int
    sum_x: int
    touches_border: bool


def _labeled_components(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise ValueError("connected-component mask must be two-dimensional")
    structure = np.array(((0, 1, 0), (1, 1, 1), (0, 1, 0)), dtype=np.uint8)
    labels, count = ndimage.label(binary, structure=structure)
    return binary, labels, int(count)


def connected_component_stats(mask: np.ndarray) -> tuple[ComponentStats, ...]:
    binary, labels, count = _labeled_components(mask)
    if not count:
        return ()
    y_values, x_values = np.nonzero(binary)
    component_labels = labels[y_values, x_values]
    sizes = np.bincount(component_labels, minlength=count + 1)
    sums_y = np.bincount(component_labels, weights=y_values, minlength=count + 1)
    sums_x = np.bincount(component_labels, weights=x_values, minlength=count + 1)
    border_labels = set(
        np.concatenate((labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1])).tolist()
    ) if binary.size else set()
    border_labels.discard(0)
    return tuple(
        ComponentStats(
            int(sizes[label]),
            int(sums_y[label]),
            int(sums_x[label]),
            label in border_labels,
        )
        for label in range(1, count + 1)
    )


def connected_components(mask: np.ndarray) -> tuple[tuple[tuple[int, int], ...], ...]:
    _binary, labels, count = _labeled_components(mask)
    return tuple(
        tuple((int(y), int(x)) for y, x in np.argwhere(labels == label))
        for label in range(1, count + 1)
    )


def nuclear_features(
    rgb: np.ndarray,
    grid: PhysicalGrid | None = None,
    *,
    hematoxylin: np.ndarray | None = None,
) -> tuple[float, ...]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    selected_grid = grid or PhysicalGrid(0.25, 0.25)
    pixel_area_um2 = selected_grid.mpp_x * selected_grid.mpp_y
    minimum_pixels = max(1, int(np.ceil(0.25 / pixel_area_um2)))
    maximum_pixels = max(minimum_pixels, int(np.floor(128.0 / pixel_area_um2)))
    hematoxylin = (
        hematoxylin_concentration(pixels)
        if hematoxylin is None
        else np.asarray(hematoxylin, dtype=np.float64)
    )
    if hematoxylin.shape != pixels.shape[:2]:
        raise ValueError("nuclear hematoxylin field does not match RGB pixels")
    objects = [
        component
        for component in connected_component_stats(hematoxylin > 0.55)
        if minimum_pixels <= component.size <= maximum_pixels
    ]
    area = sum(component.size for component in objects)
    if objects:
        centroid_y = sum(component.sum_y / component.size for component in objects) / len(
            objects
        )
        centroid_x = sum(component.sum_x / component.size for component in objects) / len(
            objects
        )
    else:
        centroid_y = centroid_x = 0.0
    height, width = hematoxylin.shape
    spatial = tuple(
        float(block.mean()) if block.size else 0.0
        for y_indices in np.array_split(np.arange(height), 4)
        for x_indices in np.array_split(np.arange(width), 4)
        for block in (hematoxylin[np.ix_(y_indices, x_indices)],)
    )
    return (
        float(len(objects)) * 1_000_000.0 / (height * width * pixel_area_um2),
        area / (height * width),
        centroid_y / max(height - 1, 1),
        centroid_x / max(width - 1, 1),
        float(hematoxylin.mean()),
        float(np.quantile(hematoxylin, 0.95)),
        float(np.quantile(hematoxylin, 0.99)),
        *boundary_spectrum(hematoxylin, selected_grid),
        *chromatin_frequency(hematoxylin, selected_grid),
        *spatial,
    )
