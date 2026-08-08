from __future__ import annotations

import numpy as np
from PIL import Image

from denser.core.models import TileAddress
from denser.wsi.reader import open_slide


def test_edge_region_is_exact_requested_shape(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pixels = np.zeros((10, 10, 3), dtype=np.uint8)
    pixels[:, :] = [30, 60, 90]
    path = tmp_path / "synthetic.png"
    Image.fromarray(pixels, mode="RGB").save(path)
    reader = open_slide(path)
    tile = reader.read_level0_region(TileAddress(0, 8, 8, 4, 4))
    assert tile.shape == (4, 4, 3)
    assert tile.dtype == np.uint8
    assert tile[0, 0].tolist() == [30, 60, 90]
    assert tile[3, 3].tolist() == [255, 255, 255]


def test_active_reader_exposes_pyramid_metadata(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "synthetic.png"
    Image.new("RGB", (7, 5), (1, 2, 3)).save(path)
    reader = open_slide(path)
    assert reader.level_dimensions == ((7, 5),)
    assert reader.codec_metadata["backend"] == "pillow-fixture"
