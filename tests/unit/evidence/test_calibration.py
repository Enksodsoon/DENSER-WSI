from __future__ import annotations

from denser.evidence.calibrate import calibrate_contract, verify_calibration
from denser.evidence.controls import CalibrationProfile, ControlPair


def _benign_pairs() -> list[ControlPair]:
    return [
        ControlPair(f"benign-{index}", f"tile-{index}", "benign", None, (
            ("nuclear_objects", (0.01 * index, 0.02 * index)),
            ("architecture", (0.005 * index, 0.01 * index)),
        ))
        for index in range(1, 7)
    ]


def _profile() -> CalibrationProfile:
    return CalibrationProfile(
        alpha=0.10,
        challenge_control_ids=("delete-small", "shift-boundary"),
    )


def test_calibration_uses_tile_level_max_statistic() -> None:
    record = calibrate_contract(_benign_pairs(), _profile())
    assert record.threshold_basis == "tile_familywise_max"
    assert all(value > 0 for _group, value in record.thresholds)


def test_challenge_controls_are_not_used_to_fit_thresholds() -> None:
    record = calibrate_contract(_benign_pairs(), _profile())
    assert set(record.fit_control_ids).isdisjoint(record.challenge_control_ids)


def test_harmful_pair_in_fit_data_is_rejected() -> None:
    pairs = _benign_pairs()
    pairs.append(
        ControlPair("harmful", "tile-x", "harmful", "architecture", (("architecture", (9.0, 9.0)),))
    )
    try:
        calibrate_contract(pairs, _profile())
    except ValueError as error:
        assert "benign" in str(error)
    else:
        raise AssertionError("harmful control entered calibration fit")


def test_undetected_required_challenge_is_not_evaluable() -> None:
    record = calibrate_contract(_benign_pairs(), _profile())
    challenges = [
        ControlPair("delete-small", "challenge-1", "harmful", "nuclear_objects", (("nuclear_objects", (9.0, 9.0)),)),
        ControlPair("shift-boundary", "challenge-2", "harmful", "architecture", (("architecture", (0.0175, 0.035)),)),
    ]
    audit = verify_calibration(record, challenges)
    assert audit.status == "not_evaluable"
    assert "shift-boundary" in audit.missed_control_ids


def test_all_required_challenges_can_freeze() -> None:
    record = calibrate_contract(_benign_pairs(), _profile())
    challenges = [
        ControlPair("delete-small", "challenge-1", "harmful", "nuclear_objects", (("nuclear_objects", (9.0, 9.0)),)),
        ControlPair("shift-boundary", "challenge-2", "harmful", "architecture", (("architecture", (9.0, 9.0)),)),
    ]
    audit = verify_calibration(record, challenges)
    assert audit.status == "calibrated"
    assert audit.missed_control_ids == ()
