from __future__ import annotations

from collections.abc import Iterator

from denser.core.models import TileAddress


def iter_level0_grid(width: int, height: int, tile_size: int) -> Iterator[TileAddress]:
    if width <= 0 or height <= 0 or tile_size <= 0:
        raise ValueError("width, height, and tile_size must be positive")
    for y in range(0, height, tile_size):
        for x in range(0, width, tile_size):
            yield TileAddress(
                level=0,
                x=x,
                y=y,
                width=min(tile_size, width - x),
                height=min(tile_size, height - y),
            )
