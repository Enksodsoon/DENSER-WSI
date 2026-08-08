from __future__ import annotations

import math
from collections.abc import Mapping


class MetadataError(ValueError):
    """Physical slide metadata is absent, invalid, or inconsistent."""


def resolve_mpp(
    properties: Mapping[str, str], *, relative_tolerance: float = 0.10
) -> float:
    try:
        mpp_x = float(properties["openslide.mpp-x"])
        mpp_y = float(properties["openslide.mpp-y"])
    except KeyError as error:
        raise MetadataError("physical MPP metadata is missing") from error
    except ValueError as error:
        raise MetadataError("physical MPP metadata is invalid") from error
    if not all(math.isfinite(value) and 0.05 <= value <= 5.0 for value in (mpp_x, mpp_y)):
        raise MetadataError("physical MPP metadata is outside supported bounds")
    average = (mpp_x + mpp_y) / 2
    if abs(mpp_x - mpp_y) / average > relative_tolerance:
        raise MetadataError("physical MPP axes are inconsistent")
    return average
