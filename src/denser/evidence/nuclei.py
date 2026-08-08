from __future__ import annotations

import numpy as np


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


def nuclear_features(rgb: np.ndarray) -> tuple[float, ...]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    intensity = pixels.astype(np.float64).mean(axis=2)
    objects = [component for component in connected_components(intensity < 140) if len(component) >= 20]
    area = sum(len(component) for component in objects)
    if objects:
        centroid_y = sum(sum(y for y, _x in component) / len(component) for component in objects) / len(objects)
        centroid_x = sum(sum(x for _y, x in component) / len(component) for component in objects) / len(objects)
    else:
        centroid_y = centroid_x = 0.0
    height, width = intensity.shape
    return (
        float(len(objects)),
        area / (height * width),
        centroid_y / max(height - 1, 1),
        centroid_x / max(width - 1, 1),
    )
