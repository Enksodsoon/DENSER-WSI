from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ControlPair:
    control_id: str
    tile_id: str
    kind: str
    expected_group: str | None
    group_deltas: tuple[tuple[str, tuple[float, ...]], ...]

    def __post_init__(self) -> None:
        if self.kind not in {"benign", "harmful"}:
            raise ValueError("control kind must be benign or harmful")
        if self.kind == "harmful" and not self.expected_group:
            raise ValueError("harmful controls require an expected group")
        if len({name for name, _values in self.group_deltas}) != len(self.group_deltas):
            raise ValueError("control groups must be unique")


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    alpha: float
    challenge_control_ids: tuple[str, ...]
    version: str = "HE-V1-calibration-1"

    def __post_init__(self) -> None:
        if not 0 < self.alpha < 0.5:
            raise ValueError("calibration alpha must be between zero and 0.5")
        if len(set(self.challenge_control_ids)) != len(self.challenge_control_ids):
            raise ValueError("challenge control identifiers must be unique")


@dataclass(frozen=True, slots=True)
class GroupStandardization:
    group: str
    centers: tuple[float, ...]
    scales: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    version: str
    threshold_basis: str
    alpha: float
    standardization: tuple[GroupStandardization, ...]
    thresholds: tuple[tuple[str, float], ...]
    fit_control_ids: tuple[str, ...]
    challenge_control_ids: tuple[str, ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class CalibrationAudit:
    status: str
    detected_control_ids: tuple[str, ...]
    missed_control_ids: tuple[str, ...]
    scores: tuple[tuple[str, float], ...]
