from __future__ import annotations

from denser.wsi.grid import iter_level0_grid


def test_grid_covers_each_pixel_exactly_once() -> None:
    grid = list(iter_level0_grid(1000, 700, 512))
    assert sum(tile.width * tile.height for tile in grid) == 700_000
    assert len({(tile.x, tile.y) for tile in grid}) == len(grid)


def test_grid_is_row_major_with_exact_edge_shapes() -> None:
    grid = list(iter_level0_grid(5, 3, 2))
    assert [(tile.x, tile.y) for tile in grid] == [
        (0, 0), (2, 0), (4, 0),
        (0, 2), (2, 2), (4, 2),
    ]
    assert [(tile.width, tile.height) for tile in grid[-3:]] == [(2, 1), (2, 1), (1, 1)]


def test_grid_rejects_invalid_dimensions() -> None:
    for args in ((0, 10, 2), (10, 0, 2), (10, 10, 0)):
        try:
            list(iter_level0_grid(*args))
        except ValueError:
            continue
        raise AssertionError(f"grid accepted invalid dimensions: {args}")
