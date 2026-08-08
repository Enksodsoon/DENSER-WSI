from __future__ import annotations

from denser.evidence.calibrate import (
    acceptance_contract_from_calibration,
    calibrate_contract,
    calibration_record_from_dict,
    verify_calibration,
)
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


def test_calibration_produces_frozen_absolute_group_bounds() -> None:
    record = calibrate_contract(_benign_pairs(), _profile())
    try:
        acceptance_contract_from_calibration(record)
    except ValueError as error:
        assert "groups" in str(error)

    complete_pairs = [
        ControlPair(
            f"complete-{index}",
            f"tile-{index}",
            "benign",
            None,
            tuple((name, (0.01 * index,)) for name in (
                "nuclear_objects", "architecture", "rare_event_sentinels", "visual"
            )),
        )
        for index in range(1, 7)
    ]
    complete = calibrate_contract(complete_pairs, _profile())
    contract = acceptance_contract_from_calibration(complete)
    assert contract.calibration_digest == complete.sha256
    assert {name for name, _bounds in contract.absolute_group_bounds} == {
        "nuclear_objects", "architecture", "rare_event_sentinels", "visual"
    }
    assert all(bound > 0 for _name, bounds in contract.absolute_group_bounds for bound in bounds)


def test_calibration_record_round_trips_through_canonical_mapping() -> None:
    from dataclasses import asdict

    record = calibrate_contract(_benign_pairs(), _profile())
    assert calibration_record_from_dict(asdict(record)) == record


def test_calibration_record_rejects_tampered_digest() -> None:
    from dataclasses import asdict

    record = calibrate_contract(_benign_pairs(), _profile())
    document = asdict(record)
    document["sha256"] = "0" * 64
    try:
        calibration_record_from_dict(document)
    except ValueError as error:
        assert "digest" in str(error)
    else:
        raise AssertionError("tampered calibration digest was accepted")
