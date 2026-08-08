from __future__ import annotations

import numpy as np
import pytest
from PIL import ImageCms

from denser.wsi.color import ColorPolicy, canonicalize_rgb
from denser.wsi.metadata import MetadataError, resolve_mpp


def test_missing_profile_is_recorded_without_enhancement() -> None:
    rgb = np.array([[[10, 20, 30]]], dtype=np.uint8)
    result = canonicalize_rgb(rgb, None, ColorPolicy())
    assert result.status == "profile_missing"
    assert np.array_equal(result.rgb, rgb)
    assert result.rgb is not rgb


def test_alpha_is_composited_onto_white_and_removed() -> None:
    rgba = np.array([[[200, 100, 0, 0], [20, 40, 60, 255]]], dtype=np.uint8)
    result = canonicalize_rgb(rgba, None, ColorPolicy())
    assert result.rgb.shape == (1, 2, 3)
    assert result.rgb[0, 0].tolist() == [255, 255, 255]
    assert result.rgb[0, 1].tolist() == [20, 40, 60]


def test_valid_profile_is_converted_to_pinned_srgb() -> None:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    rgb = np.array([[[10, 20, 30], [240, 220, 200]]], dtype=np.uint8)
    result = canonicalize_rgb(rgb, profile, ColorPolicy())
    assert result.status == "profile_converted"
    assert result.output_space == "sRGB IEC61966-2.1"
    assert len(result.source_icc_sha256 or "") == 64


def test_invalid_profile_fails_closed_when_required() -> None:
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="ICC"):
        canonicalize_rgb(rgb, b"not-an-icc-profile", ColorPolicy(require_valid=True))


def test_mpp_requires_consistent_physical_scale() -> None:
    assert resolve_mpp({"openslide.mpp-x": "0.25", "openslide.mpp-y": "0.26"}) == pytest.approx(0.255)
    with pytest.raises(MetadataError, match="inconsistent"):
        resolve_mpp({"openslide.mpp-x": "0.25", "openslide.mpp-y": "0.50"})


def test_mpp_missing_is_explicit() -> None:
    with pytest.raises(MetadataError, match="missing"):
        resolve_mpp({})
