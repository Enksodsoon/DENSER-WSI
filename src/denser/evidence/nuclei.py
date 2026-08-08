from __future__ import annotations

from collections import deque

import numpy as np


def connected_components(mask: np.ndarray) -> tuple[tuple[tuple[int, int], ...], ...]:
    binary = np.asarray(mask, dtype=bool)
    visited = np.zeros(binary.shape, dtype=bool)
    components: list[tuple[tuple[int, int], ...]] = []
    height, width = binary.shape
    for start_y in range(height):
        for start_x in range(width):
            if not binary[start_y, start_x] or visited[start_y, start_x]:
                continue
            queue = deque([(start_y, start_x)])
            visited[start_y, start_x] = True
            points: list[tuple[int, int]] = []
            while queue:
                y, x = queue.popleft()
                points.append((y, x))
                for next_y, next_x in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if (
                        0 <= next_y < height
                        and 0 <= next_x < width
                        and binary[next_y, next_x]
                        and not visited[next_y, next_x]
                    ):
                        visited[next_y, next_x] = True
                        queue.append((next_y, next_x))
            components.append(tuple(points))
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
