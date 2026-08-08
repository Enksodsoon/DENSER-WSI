from __future__ import annotations

import numpy as np
import pytest

from denser.evidence.controls_v1 import (
    BENIGN_CONTROLS,
    HARMFUL_CONTROLS,
    build_control_cohort,
    build_balanced_control_cohort,
    build_control_pair,
    transform_control,
    verify_control_configuration,
)
from denser.evidence.calibrate import calibrate_contract, verify_calibration
from denser.evidence.controls import CalibrationProfile
from denser.evidence.types import PhysicalGrid


def _histology_tile() -> np.ndarray:
    rgb = np.full((96, 96, 3), 248, dtype=np.uint8)
    y, x = np.mgrid[:96, :96]
    tissue = (x - 48) ** 2 + (y - 48) ** 2 < 42**2
    nuclei = ((x % 15) - 7) ** 2 + ((y % 15) - 7) ** 2 < 4**2
    rgb[tissue] = (211, 145, 183)
    rgb[tissue & nuclei] = (68, 31, 92)
    rgb[31:34, 67:70] = (28, 15, 39)
    rgb[42:54, 42:54] = (252, 252, 252)
    return rgb


def test_controls_are_deterministic_and_do_not_mutate_source() -> None:
    source = _histology_tile()
    before = source.copy()
    for name in (*BENIGN_CONTROLS, *HARMFUL_CONTROLS):
        first = transform_control(source, name, seed=17)
        second = transform_control(source, name, seed=17)
        assert np.array_equal(first, second)
        assert first.dtype == np.uint8
        assert first.shape == source.shape
    assert np.array_equal(source, before)


def test_control_pairs_report_every_he_v1_group() -> None:
    source = _histology_tile()
    pair = build_control_pair(
        source,
        tile_id="development-tile-001",
        control_name="sensor_noise_1",
        grid=PhysicalGrid(0.25, 0.25),
        seed=4,
    )
    assert pair.kind == "benign"
    assert {name for name, _values in pair.group_deltas} == {
        "nuclear_objects",
        "architecture",
        "rare_event_sentinels",
        "visual",
    }


def test_harmful_controls_change_their_declared_group() -> None:
    source = _histology_tile()
    for name, expected_group in HARMFUL_CONTROLS.items():
        pair = build_control_pair(
            source,
            tile_id=f"challenge-{name}",
            control_name=name,
            grid=PhysicalGrid(0.25, 0.25),
            seed=9,
        )
        values = dict(pair.group_deltas)[expected_group]
        assert max(values) > 0


def test_control_cohort_keeps_fit_and_challenge_tiles_disjoint() -> None:
    tiles = [(_histology_tile(), f"tile-{index}") for index in range(9)]
    benign, harmful = build_control_cohort(
        tiles, PhysicalGrid(0.25, 0.25), seed=11
    )
    assert len(benign) == 4
    assert len(harmful) == len(HARMFUL_CONTROLS)
    assert {pair.tile_id for pair in benign}.isdisjoint(
        pair.tile_id for pair in harmful
    )


def test_he_v1_calibration_retains_all_predeclared_harmful_controls() -> None:
    base = _histology_tile()
    tiles = [
        (np.roll(base, shift=(index % 3, index % 5), axis=(0, 1)), f"tile-{index}")
        for index in range(35)
    ]
    benign, harmful = build_control_cohort(
        tiles, PhysicalGrid(0.25, 0.25), seed=27
    )
    profile = CalibrationProfile(0.05, tuple(pair.control_id for pair in harmful))
    record = calibrate_contract(list(benign), profile)
    audit = verify_calibration(record, list(harmful))
    assert audit.status == "calibrated"
    assert audit.missed_control_ids == ()


def test_balanced_controls_use_distinct_slides_and_disjoint_fit_tiles() -> None:
    base = _histology_tile()
    slides = [
        [
            (
                np.roll(base, shift=(slide, tile), axis=(0, 1)),
                f"slide-{slide}-tile-{tile}",
                PhysicalGrid(0.25, 0.25),
            )
            for tile in range(4)
        ]
        for slide in range(6)
    ]
    benign, harmful = build_balanced_control_cohort(slides, seed=41)
    assert len(harmful) == len(HARMFUL_CONTROLS)
    assert len({pair.tile_id.split("-tile-")[0] for pair in harmful}) == len(harmful)
    assert {pair.tile_id for pair in benign}.isdisjoint(pair.tile_id for pair in harmful)


def test_frozen_control_configuration_rejects_parameter_drift() -> None:
    import json
    from pathlib import Path

    document = json.loads(
        Path("configs/experiment/he_v1_controls.json").read_text(encoding="utf-8")
    )
    verify_control_configuration(document)
    document["harmful_controls"][0]["radius_um"] = 3.0
    with pytest.raises(ValueError, match="harmful controls"):
        verify_control_configuration(document)
