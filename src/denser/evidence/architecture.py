from __future__ import annotations

import hashlib

import numpy as np

from denser.core.canonical import canonical_json_bytes
from denser.evidence.nuclei import connected_components, nuclear_features
from denser.evidence.sentinels import sentinel_features
from denser.evidence.types import (
    AcceptanceComparison,
    AcceptanceContract,
    AcceptanceEvidence,
    PhysicalGrid,
)
from denser.evidence.visual import visual_features


def architecture_features(rgb: np.ndarray) -> tuple[float, ...]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    bright = np.all(pixels > 245, axis=2)
    height, width = bright.shape
    enclosed = []
    for component in connected_components(bright):
        touches_border = any(y in (0, height - 1) or x in (0, width - 1) for y, x in component)
        if not touches_border and len(component) >= 4:
            enclosed.append(component)
    lumen_area = sum(len(component) for component in enclosed)
    tissue_fraction = float((pixels.astype(np.float64).mean(axis=2) < 240).mean())
    return (float(len(enclosed)), lumen_area / bright.size, tissue_fraction)


def compute_acceptance_evidence(
    rgb: np.ndarray, physical_grid: PhysicalGrid, contract: AcceptanceContract
) -> AcceptanceEvidence:
    groups = (
        ("nuclear_objects", nuclear_features(rgb)),
        ("architecture", architecture_features(rgb)),
        ("rare_event_sentinels", sentinel_features(rgb)),
        ("visual", visual_features(rgb)),
    )
    rounded = tuple(
        (name, tuple(round(float(value), 12) for value in values))
        for name, values in groups
    )
    document = {
        "version": contract.version,
        "mpp": [physical_grid.mpp_x, physical_grid.mpp_y],
        "groups": rounded,
    }
    digest = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    return AcceptanceEvidence(contract.version, rounded, digest)


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
    tolerances = {
        "nuclear_objects": contract.nuclear_relative_tolerance,
        "architecture": contract.architecture_relative_tolerance,
        "rare_event_sentinels": contract.sentinel_relative_tolerance,
        "visual": contract.visual_relative_tolerance,
    }
    candidate_groups = dict(candidate.groups)
    distances = tuple(
        (name, _relative_distance(values, candidate_groups[name]))
        for name, values in reference.groups
    )
    failed = tuple(name for name, distance in distances if distance > tolerances[name])
    return AcceptanceComparison(distances, failed)
