from __future__ import annotations

import numpy as np
import pytest

from denser.evidence.architecture import compare_acceptance
from denser.evidence.types import AcceptanceContract, PhysicalGrid


def _challenge_pair(control: str) -> tuple[np.ndarray, np.ndarray]:
    source = np.full((64, 64, 3), 250, dtype=np.uint8)
    y, x = np.mgrid[:64, :64]
    tissue = (x - 32) ** 2 + (y - 32) ** 2 <= 24**2
    nucleus = (x - 24) ** 2 + (y - 30) ** 2 <= 8**2
    lumen = (x - 39) ** 2 + (y - 33) ** 2 <= 6**2
    source[tissue] = [215, 145, 185]
    source[nucleus] = [85, 35, 105]
    source[lumen] = [252, 252, 252]
    source[16:18, 47:49] = [35, 20, 45]
    altered = source.copy()
    if control == "delete_small_dark_object":
        altered[16:18, 47:49] = [250, 250, 250]
    elif control == "shift_nuclear_boundary":
        altered[nucleus] = [215, 145, 185]
        shifted = (x - 29) ** 2 + (y - 30) ** 2 <= 6**2
        altered[shifted] = [85, 35, 105]
    elif control == "collapse_lumen":
        altered[lumen] = [215, 145, 185]
    else:
        raise ValueError(control)
    return source, altered


@pytest.mark.parametrize(
    ("control", "group"),
    [
        ("delete_small_dark_object", "rare_event_sentinels"),
        ("shift_nuclear_boundary", "nuclear_objects"),
        ("collapse_lumen", "architecture"),
    ],
)
def test_harmful_control_is_detected(control: str, group: str) -> None:
    source, altered = _challenge_pair(control)
    result = compare_acceptance(
        source, altered, PhysicalGrid(0.25, 0.25), AcceptanceContract()
    )
    assert group in result.failed_groups


def test_identical_image_passes_all_acceptance_groups() -> None:
    source, _ = _challenge_pair("collapse_lumen")
    result = compare_acceptance(
        source, source.copy(), PhysicalGrid(0.25, 0.25), AcceptanceContract()
    )
    assert result.failed_groups == ()
