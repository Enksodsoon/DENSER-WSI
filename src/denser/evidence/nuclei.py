from __future__ import annotations

import numpy as np

from denser.evidence.stain import (
    boundary_spectrum,
    chromatin_frequency,
    hematoxylin_concentration,
)
from denser.evidence.types import PhysicalGrid


def connected_components(mask: np.ndarray) -> tuple[tuple[tuple[int, int], ...], ...]:
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise ValueError("connected-component mask must be two-dimensional")
    runs: list[tuple[int, int, int]] = []
    parents: list[int] = []

    def find(index: int) -> int:
        root = index
        while parents[root] != root:
            root = parents[root]
        while parents[index] != index:
            parent = parents[index]
            parents[index] = root
            index = parent
        return root

    def union(first: int, second: int) -> None:
        left = find(first)
        right = find(second)
        if left != right:
            parents[max(left, right)] = min(left, right)

    previous: list[int] = []
    for y, row in enumerate(binary):
        transitions = np.diff(np.pad(row.astype(np.int8), (1, 1)))
        starts = np.flatnonzero(transitions == 1)
        ends = np.flatnonzero(transitions == -1)
        current: list[int] = []
        previous_cursor = 0
        for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
            index = len(runs)
            runs.append((y, start, end))
            parents.append(index)
            current.append(index)
            while previous_cursor < len(previous) and runs[previous[previous_cursor]][2] <= start:
                previous_cursor += 1
            overlap_cursor = previous_cursor
            while overlap_cursor < len(previous):
                previous_index = previous[overlap_cursor]
                _previous_y, previous_start, previous_end = runs[previous_index]
                if previous_start >= end:
                    break
                if previous_end > start:
                    union(index, previous_index)
                overlap_cursor += 1
        previous = current

    grouped: dict[int, list[int]] = {}
    for index in range(len(runs)):
        grouped.setdefault(find(index), []).append(index)
    components = []
    for indices in grouped.values():
        points = tuple(
            (y, x)
            for index in indices
            for y, start, end in (runs[index],)
            for x in range(start, end)
        )
        components.append(points)
    return tuple(components)


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
        for component in connected_components(hematoxylin > 0.55)
        if minimum_pixels <= len(component) <= maximum_pixels
    ]
    area = sum(len(component) for component in objects)
    if objects:
        centroid_y = sum(sum(y for y, _x in component) / len(component) for component in objects) / len(objects)
        centroid_x = sum(sum(x for _y, x in component) / len(component) for component in objects) / len(objects)
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
