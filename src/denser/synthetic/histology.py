from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from denser.core.models import TileAddress


@dataclass(frozen=True, slots=True)
class SyntheticSlideSpec:
    width: int = 256
    height: int = 256
    tile_size: int = 64
    mpp: float = 0.25
    nuclei: int = 80
    glands: int = 6
    rare_dark_objects: int = 4

    def __post_init__(self) -> None:
        if min(self.width, self.height, self.tile_size) <= 0:
            raise ValueError("synthetic dimensions must be positive")
        if self.width % self.tile_size or self.height % self.tile_size:
            raise ValueError("synthetic dimensions must be multiples of tile_size")
        if min(self.nuclei, self.glands, self.rare_dark_objects) <= 0:
            raise ValueError("synthetic feature counts must be positive")


@dataclass(frozen=True, slots=True)
class SyntheticSlide:
    pixels: np.ndarray
    spec: SyntheticSlideSpec
    seed: int
    sha256: str
    feature_counts: dict[str, int]
    perturbations: tuple[str, ...]

    def tiles(self) -> tuple[tuple[TileAddress, np.ndarray], ...]:
        values: list[tuple[TileAddress, np.ndarray]] = []
        for x in range(0, self.spec.width, self.spec.tile_size):
            for y in range(0, self.spec.height, self.spec.tile_size):
                address = TileAddress(0, x, y, self.spec.tile_size, self.spec.tile_size)
                tile = self.pixels[y : y + self.spec.tile_size, x : x + self.spec.tile_size].copy()
                values.append((address, tile))
        return tuple(values)


def _ellipse_mask(
    yy: np.ndarray, xx: np.ndarray, cx: int, cy: int, rx: int, ry: int
) -> np.ndarray:
    return ((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2 <= 1


def generate_synthetic_slide(spec: SyntheticSlideSpec, seed: int) -> SyntheticSlide:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[: spec.height, : spec.width]
    background = np.empty((spec.height, spec.width, 3), dtype=np.uint8)
    texture = rng.normal(0, 4, size=(spec.height, spec.width, 1))
    base = np.array([224, 176, 202], dtype=np.float64)
    background[:] = np.clip(base + texture, 0, 255).astype(np.uint8)
    background[: spec.height // 8, : spec.width // 5] = 255

    for _ in range(spec.glands):
        cx = int(rng.integers(10, max(11, spec.width - 10)))
        cy = int(rng.integers(10, max(11, spec.height - 10)))
        rx = int(rng.integers(5, max(6, min(14, spec.width // 4))))
        ry = int(rng.integers(5, max(6, min(14, spec.height // 4))))
        outer = _ellipse_mask(yy, xx, cx, cy, rx, ry)
        inner = _ellipse_mask(yy, xx, cx, cy, max(2, rx - 3), max(2, ry - 3))
        background[outer] = np.array([174, 94, 151], dtype=np.uint8)
        background[inner] = np.array([248, 234, 241], dtype=np.uint8)

    for _ in range(spec.nuclei):
        cx = int(rng.integers(2, spec.width - 2))
        cy = int(rng.integers(2, spec.height - 2))
        nucleus = _ellipse_mask(yy, xx, cx, cy, int(rng.integers(1, 3)), int(rng.integers(1, 3)))
        background[nucleus] = np.array([67, 34, 105], dtype=np.uint8)

    for _ in range(spec.rare_dark_objects):
        cx = int(rng.integers(1, spec.width - 1))
        cy = int(rng.integers(1, spec.height - 1))
        background[cy - 1 : cy + 2, cx - 1 : cx + 2] = np.array([15, 8, 25], dtype=np.uint8)

    background.flags.writeable = False
    digest = hashlib.sha256(background.tobytes(order="C")).hexdigest()
    return SyntheticSlide(
        background,
        spec,
        seed,
        digest,
        {"nuclei": spec.nuclei, "glands": spec.glands, "rare_dark_objects": spec.rare_dark_objects},
        ("nuclear_edge_blur", "small_object_deletion", "local_colour_collapse"),
    )
