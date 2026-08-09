from __future__ import annotations

import pytest

from scripts.calibrate_private_development import _mpp
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
