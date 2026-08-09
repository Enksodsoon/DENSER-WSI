from __future__ import annotations

import hashlib

import numpy as np

from denser.core.canonical import canonical_json_bytes
from denser.evidence.nuclei import connected_component_stats, nuclear_features
from denser.evidence.sentinels import sentinel_features
from denser.evidence.stain import hematoxylin_concentration
from denser.evidence.types import (
    AcceptanceComparison,
    AcceptanceContract,
    AcceptanceEvidence,
    PhysicalGrid,
)
from denser.evidence.visual import visual_features


def architecture_features(
    rgb: np.ndarray, physical_grid: PhysicalGrid | None = None
) -> tuple[float, ...]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    grid = physical_grid or PhysicalGrid(0.25, 0.25)
    minimum_lumen_pixels = max(
        1, int(np.ceil(0.25 / (grid.mpp_x * grid.mpp_y)))
    )
    bright = np.all(pixels > 245, axis=2)
    enclosed = [
        component
        for component in connected_component_stats(bright)
        if not component.touches_border and component.size >= minimum_lumen_pixels
    ]
    lumen_area = sum(component.size for component in enclosed)
    tissue_fraction = float((pixels.astype(np.float64).mean(axis=2) < 240).mean())
    return (float(len(enclosed)), lumen_area / bright.size, tissue_fraction)


def compute_acceptance_evidence(
    rgb: np.ndarray,
    physical_grid: PhysicalGrid,
    contract: AcceptanceContract,
    *,
    groups: tuple[str, ...] | None = None,
) -> AcceptanceEvidence:
    rounded = compute_acceptance_groups(
        rgb, physical_grid, groups=groups
    )
    document = {
        "version": contract.version,
        "mpp": [physical_grid.mpp_x, physical_grid.mpp_y],
        "groups": rounded,
    }
    digest = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    return AcceptanceEvidence(contract.version, rounded, digest)


def compute_acceptance_groups(
    rgb: np.ndarray,
    physical_grid: PhysicalGrid,
    *,
    groups: tuple[str, ...] | None = None,
) -> tuple[tuple[str, tuple[float, ...]], ...]:
    ordered_names = (
        "nuclear_objects",
        "architecture",
        "rare_event_sentinels",
        "visual",
    )
    selected = set(ordered_names if groups is None else groups)
    if not selected or not selected.issubset(ordered_names):
        raise ValueError("unknown or empty acceptance group selection")
    hematoxylin = (
        hematoxylin_concentration(rgb)
        if selected.intersection({"nuclear_objects", "rare_event_sentinels"})
        else None
    )
    extracted = []
    for name in ordered_names:
        if name not in selected:
            continue
        if name == "nuclear_objects":
            values = nuclear_features(
                rgb, physical_grid, hematoxylin=hematoxylin
            )
        elif name == "architecture":
            values = architecture_features(rgb, physical_grid)
        elif name == "rare_event_sentinels":
            values = sentinel_features(
                rgb, physical_grid, hematoxylin=hematoxylin
            )
        else:
            values = visual_features(rgb)
        extracted.append((name, values))
    rounded = tuple(
        (name, tuple(round(float(value), 12) for value in values))
        for name, values in extracted
    )
    return rounded


def _relative_distance(reference: tuple[float, ...], candidate: tuple[float, ...]) -> float:
    first = np.asarray(reference, dtype=np.float64)
    second = np.asarray(candidate, dtype=np.float64)
    scale = np.maximum(np.abs(first), 1e-6)
    return float(np.max(np.abs(first - second) / scale))


def compare_acceptance(
    source: np.ndarray,
    decoded: np.ndarray,
    physical_grid: PhysicalGrid,
    contract: AcceptanceContract,
) -> AcceptanceComparison:
    reference = compute_acceptance_evidence(source, physical_grid, contract)
    candidate = compute_acceptance_evidence(decoded, physical_grid, contract)
    return compare_evidence(reference, candidate, contract)


def compare_evidence(
    reference: AcceptanceEvidence,
    candidate: AcceptanceEvidence,
    contract: AcceptanceContract,
) -> AcceptanceComparison:
    if reference.version != contract.version or candidate.version != contract.version:
        raise ValueError("evidence version does not match acceptance contract")
    return compare_acceptance_groups(reference.groups, candidate.groups, contract)


def compare_acceptance_groups(
    reference_groups: tuple[tuple[str, tuple[float, ...]], ...],
    candidate_group_values: tuple[tuple[str, tuple[float, ...]], ...],
    contract: AcceptanceContract,
) -> AcceptanceComparison:
    calibrated = dict(contract.absolute_group_bounds)
    tolerances = {
        "nuclear_objects": contract.nuclear_relative_tolerance,
        "architecture": contract.architecture_relative_tolerance,
        "rare_event_sentinels": contract.sentinel_relative_tolerance,
        "visual": contract.visual_relative_tolerance,
    }
    candidate_groups = dict(candidate_group_values)
    if set(candidate_groups) != {name for name, _values in reference_groups}:
        raise ValueError("candidate evidence groups do not match reference")
    distances = []
    failed = []
    for name, values in reference_groups:
        if calibrated:
            bounds = np.asarray(calibrated[name], dtype=np.float64)
            first = np.asarray(values, dtype=np.float64)
            second = np.asarray(candidate_groups[name], dtype=np.float64)
            if bounds.shape != first.shape:
                raise ValueError("calibrated bound shape does not match evidence group")
            distance = float(np.max(np.abs(first - second) / bounds))
            threshold = 1.0
        else:
            distance = _relative_distance(values, candidate_groups[name])
            threshold = tolerances[name]
        distances.append((name, distance))
        if distance > threshold:
            failed.append(name)
    return AcceptanceComparison(tuple(distances), tuple(failed))
