from __future__ import annotations

import numpy as np

from denser.evidence.nuclei import connected_components


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
