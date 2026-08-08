from __future__ import annotations

import numpy as np

from denser.evidence.nuclei import connected_component_stats, connected_components


def test_components_preserve_four_connectivity_and_row_major_order() -> None:
    mask = np.array(
        [
            [1, 1, 0, 0],
            [0, 1, 0, 1],
            [1, 0, 0, 1],
            [1, 1, 0, 0],
        ],
        dtype=bool,
    )
    assert connected_components(mask) == (
        ((0, 0), (0, 1), (1, 1)),
        ((1, 3), (2, 3)),
        ((2, 0), (3, 0), (3, 1)),
    )


def test_dense_component_preserves_every_point() -> None:
    component = connected_components(np.ones((32, 32), dtype=bool))
    assert len(component) == 1
    assert len(component[0]) == 32 * 32


def test_component_statistics_match_materialized_components() -> None:
    rng = np.random.default_rng(20260808)
    for shape in ((1, 1), (7, 11), (32, 32)):
        mask = rng.random(shape) > 0.62
        components = connected_components(mask)
        expected = sorted(
            (
                len(component),
                sum(y for y, _x in component),
                sum(x for _y, x in component),
                any(
                    y in (0, shape[0] - 1) or x in (0, shape[1] - 1)
                    for y, x in component
                ),
            )
            for component in components
        )
        observed = sorted(
            (value.size, value.sum_y, value.sum_x, value.touches_border)
            for value in connected_component_stats(mask)
        )
        assert observed == expected
