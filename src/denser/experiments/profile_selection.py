from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProfileResult:
    profile_id: str
    complete_bytes: int
    fallback_fraction: float
    evidence_passed: bool

    def __post_init__(self) -> None:
        if not self.profile_id or self.complete_bytes < 0:
            raise ValueError("profile result is invalid")
        if not 0 <= self.fallback_fraction <= 1:
            raise ValueError("fallback fraction must be between zero and one")


@dataclass(frozen=True, slots=True)
class SelectionRule:
    name: str = "lowest_complete_bytes_then_lower_fallback_fraction"

    def __post_init__(self) -> None:
        if self.name != "lowest_complete_bytes_then_lower_fallback_fraction":
            raise ValueError("profile selection rule is frozen")


@dataclass(frozen=True, slots=True)
class SelectedProfile:
    profile_id: str
    reason: str
    classification: str
    operational_fallback: str


def select_profile(
    results: tuple[ProfileResult, ...] | list[ProfileResult], rule: SelectionRule
) -> SelectedProfile:
    if not results:
        raise ValueError("profile selection requires declared results")
    passing = [row for row in results if row.evidence_passed]
    if passing:
        chosen = min(
            passing,
            key=lambda row: (row.complete_bytes, row.fallback_fraction, row.profile_id),
        )
        return SelectedProfile(
            chosen.profile_id,
            rule.name,
            "passing_profile",
            "standard-portfolio",
        )
    chosen = min(
        results,
        key=lambda row: (row.fallback_fraction, row.complete_bytes, row.profile_id),
    )
    return SelectedProfile(
        chosen.profile_id,
        "no_passing_profile_safest_then_smallest",
        "negative_evaluation",
        "standard-portfolio",
    )
