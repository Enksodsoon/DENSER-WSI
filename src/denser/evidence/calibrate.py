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
from denser.evidence.types import AcceptanceContract


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
    cell_calibration = any(pair.cell_group_deltas for pair in development_pairs)
    if cell_calibration and any(not pair.cell_group_deltas for pair in development_pairs):
        raise ValueError("cell-level calibration records cannot be mixed with tile-only records")
    grouped: dict[str, list[np.ndarray]] = {}
    for pair in development_pairs:
        values_by_group = (
            pair.cell_group_deltas if cell_calibration else pair.group_deltas
        )
        for group, values in values_by_group:
            matrix = np.asarray(values, dtype=np.float64)
            if not cell_calibration:
                matrix = matrix.reshape(1, -1)
            if matrix.ndim != 2 or not matrix.size:
                raise ValueError("calibration group values must be a non-empty matrix")
            grouped.setdefault(group, []).append(matrix)
    standardization = []
    thresholds = []
    for group in sorted(grouped):
        tile_matrices = grouped[group]
        if len(tile_matrices) != len(development_pairs):
            raise ValueError("every benign tile must report every calibrated group")
        feature_counts = {matrix.shape[1] for matrix in tile_matrices}
        if len(feature_counts) != 1:
            raise ValueError("calibrated group feature counts must match")
        matrix = np.concatenate(tile_matrices, axis=0)
        centers = np.median(matrix, axis=0)
        deviations = np.abs(matrix - centers)
        robust_scales = np.median(deviations, axis=0) * 1.4826
        benign_envelope = np.max(deviations, axis=0)
        scales = np.maximum(np.maximum(robust_scales, benign_envelope), 1e-6)
        tile_maxima = np.asarray(
            [
                np.max(np.abs(tile_matrix - centers) / scales)
                for tile_matrix in tile_matrices
            ],
            dtype=np.float64,
        )
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
        group_values = dict(
            pair.cell_group_deltas or pair.group_deltas
        ).get(pair.expected_group)
        standard = standardization.get(pair.expected_group)
        if group_values is None or standard is None:
            missed.append(control_id)
            scores.append((control_id, 0.0))
            continue
        values = np.asarray(group_values, dtype=np.float64)
        if values.ndim == 1:
            values = values.reshape(1, -1)
        centers = np.asarray(standard.centers, dtype=np.float64)
        scales = np.asarray(standard.scales, dtype=np.float64)
        if values.ndim != 2 or values.shape[1:] != centers.shape:
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


def calibration_record_from_dict(document: dict[str, object]) -> CalibrationRecord:
    try:
        standardization = tuple(
            GroupStandardization(
                str(item["group"]),
                tuple(float(value) for value in item["centers"]),
                tuple(float(value) for value in item["scales"]),
            )
            for item in document["standardization"]  # type: ignore[union-attr]
        )
        thresholds = tuple(
            (str(item[0]), float(item[1]))
            for item in document["thresholds"]  # type: ignore[union-attr]
        )
        record = CalibrationRecord(
            str(document["version"]),
            str(document["threshold_basis"]),
            float(document["alpha"]),
            standardization,
            thresholds,
            tuple(str(value) for value in document["fit_control_ids"]),  # type: ignore[union-attr]
            tuple(str(value) for value in document["challenge_control_ids"]),  # type: ignore[union-attr]
            str(document["sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("calibration record mapping is invalid") from error
    unsigned = {
        "version": record.version,
        "threshold_basis": record.threshold_basis,
        "alpha": record.alpha,
        "standardization": [asdict(item) for item in record.standardization],
        "thresholds": list(record.thresholds),
        "fit_control_ids": sorted(record.fit_control_ids),
        "challenge_control_ids": list(record.challenge_control_ids),
    }
    digest = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    if digest != record.sha256:
        raise ValueError("calibration record digest mismatch")
    return record


def acceptance_contract_from_calibration(record: CalibrationRecord) -> AcceptanceContract:
    required = {"nuclear_objects", "architecture", "rare_event_sentinels", "visual"}
    standardization = {item.group: item for item in record.standardization}
    thresholds = dict(record.thresholds)
    if set(standardization) != required or set(thresholds) != required:
        raise ValueError("calibration record does not contain all HE-V1 acceptance groups")
    bounds = []
    for name in sorted(required):
        item = standardization[name]
        threshold = thresholds[name]
        values = tuple(
            max(1e-6, abs(center) + threshold * scale)
            for center, scale in zip(item.centers, item.scales, strict=True)
        )
        bounds.append((name, values))
    return AcceptanceContract(
        calibration_digest=record.sha256,
        absolute_group_bounds=tuple(bounds),
    )
