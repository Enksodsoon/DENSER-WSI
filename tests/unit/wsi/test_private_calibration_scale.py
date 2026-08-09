from __future__ import annotations

import pytest

import numpy as np
from PIL import Image
from pathlib import Path
from types import SimpleNamespace

from scripts.calibrate_private_development import (
    _calibration_tissue_score,
    _mpp,
    _sample_tiles,
)
from denser.wsi.metadata import MetadataError


class _Slide:
    def __init__(self, mpp: str | None) -> None:
        self.properties = {} if mpp is None else {
            "openslide.mpp-x": mpp,
            "openslide.mpp-y": mpp,
        }


def test_private_calibration_accepts_primary_scale() -> None:
    assert _mpp(_Slide("0.25")).mean_mpp == 0.25


@pytest.mark.parametrize("mpp", ["0.19", "0.31", None])
def test_private_calibration_rejects_nonprimary_or_missing_scale(mpp: str | None) -> None:
    with pytest.raises(MetadataError):
        _mpp(_Slide(mpp))


def test_private_calibration_does_not_rank_uniform_gray_as_tissue() -> None:
    gray = np.full((512, 512, 3), 128, dtype=np.uint8)
    histology = gray.copy()
    histology[:, :256] = (130, 70, 150)
    assert _calibration_tissue_score(gray) == 0.0
    assert _calibration_tissue_score(histology) > 0.4


def test_private_calibration_refines_grid_when_coarse_grid_misses_tissue(
    monkeypatch,
) -> None:
    initial = {
        (int(x), int(y))
        for y in np.linspace(0, 488, 5, dtype=int)
        for x in np.linspace(0, 488, 5, dtype=int)
    }

    class _SparseSlide:
        dimensions = (1000, 1000)
        properties = {"openslide.mpp-x": "0.25", "openslide.mpp-y": "0.25"}
        reads = 0

        def read_region(self, location, level, size):  # type: ignore[no-untyped-def]
            self.reads += 1
            rgb = np.full((size[1], size[0], 3), 128, dtype=np.uint8)
            if location not in initial:
                rgb[:, : size[0] // 2] = (130, 70, 150)
            return Image.fromarray(rgb)

        def close(self) -> None:
            pass

    slide = _SparseSlide()
    monkeypatch.setitem(
        __import__("sys").modules,
        "openslide",
        SimpleNamespace(OpenSlide=lambda _path: slide),
    )
    selected = _sample_tiles(Path("unused.svs"), 4, 5)
    assert slide.reads > 25
    assert all(_calibration_tissue_score(rgb) >= 0.10 for rgb, _grid in selected)
