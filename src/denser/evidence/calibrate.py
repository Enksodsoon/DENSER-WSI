from __future__ import annotations

import hashlib
import math
from dataclasses import asdict

import numpy as np

from denser.core.canonical import canonical_json_bytes
from denser.evidence.controls import (
    CalibrationAudit,
    CalibrationProfile,
    CalibrationRecord,
    ControlPair,
    GroupStandardization,
)


def _finite_quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, math.ceil((len(ordered) + 1) * probability) - 1))
    return float(ordered[rank])


def calibrate_contract(
    development_pairs: list[ControlPair], profile: CalibrationProfile
) -> CalibrationRecord:
    if len(development_pairs) < 2:
        raise ValueError("calibration requires at least two benign development tiles")
    if any(pair.kind != "benign" for pair in development_pairs):
        raise ValueError("only benign controls may fit calibration thresholds")
    if len({pair.tile_id for pair in development_pairs}) != len(development_pairs):
        raise ValueError("calibration requires unique tile-level records")
    grouped: dict[str, list[tuple[float, ...]]] = {}
    for pair in development_pairs:
        for group, values in pair.group_deltas:
            grouped.setdefault(group, []).append(values)
    standardization = []
    thresholds = []
    for group in sorted(grouped):
        matrix = np.asarray(grouped[group], dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[0] != len(development_pairs):
            raise ValueError("every benign tile must report every calibrated group")
        centers = np.median(matrix, axis=0)
        scales = np.maximum(np.median(np.abs(matrix - centers), axis=0) * 1.4826, 1e-6)
        tile_maxima = np.max(np.abs(matrix - centers) / scales, axis=1)
        threshold = _finite_quantile(tile_maxima.tolist(), 1 - profile.alpha)
        standardization.append(
            GroupStandardization(
                group,
                tuple(round(float(value), 12) for value in centers),
                tuple(round(float(value), 12) for value in scales),
            )
        )
        thresholds.append((group, round(threshold, 12)))
    unsigned = {
        "version": profile.version,
        "threshold_basis": "tile_familywise_max",
        "alpha": profile.alpha,
        "standardization": [asdict(item) for item in standardization],
        "thresholds": thresholds,
        "fit_control_ids": sorted(pair.control_id for pair in development_pairs),
        "challenge_control_ids": list(profile.challenge_control_ids),
    }
    digest = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    return CalibrationRecord(
        profile.version,
        "tile_familywise_max",
        profile.alpha,
        tuple(standardization),
        tuple(thresholds),
        tuple(unsigned["fit_control_ids"]),
        profile.challenge_control_ids,
        digest,
    )


def verify_calibration(
    record: CalibrationRecord, challenge_pairs: list[ControlPair]
) -> CalibrationAudit:
    standardization = {item.group: item for item in record.standardization}
    thresholds = dict(record.thresholds)
    required = set(record.challenge_control_ids)
    detected: list[str] = []
    missed: list[str] = []
    scores: list[tuple[str, float]] = []
    by_id = {pair.control_id: pair for pair in challenge_pairs}
    for control_id in record.challenge_control_ids:
        pair = by_id.get(control_id)
        if pair is None or pair.kind != "harmful" or pair.expected_group is None:
            missed.append(control_id)
            scores.append((control_id, 0.0))
            continue
        group_values = dict(pair.group_deltas).get(pair.expected_group)
        standard = standardization.get(pair.expected_group)
        if group_values is None or standard is None:
            missed.append(control_id)
            scores.append((control_id, 0.0))
            continue
        values = np.asarray(group_values, dtype=np.float64)
        centers = np.asarray(standard.centers, dtype=np.float64)
        scales = np.asarray(standard.scales, dtype=np.float64)
        if values.shape != centers.shape:
            missed.append(control_id)
            scores.append((control_id, 0.0))
            continue
        score = float(np.max(np.abs(values - centers) / scales))
        scores.append((control_id, round(score, 12)))
        if score > thresholds[pair.expected_group]:
            detected.append(control_id)
        else:
            missed.append(control_id)
    unexpected = set(by_id) - required
    if unexpected:
        raise ValueError("challenge set contains undeclared controls")
    status = "calibrated" if not missed and set(detected) == required else "not_evaluable"
    return CalibrationAudit(status, tuple(detected), tuple(missed), tuple(scores))
