from __future__ import annotations

import inspect

from denser.experiments.profile_selection import (
    ProfileResult,
    SelectionRule,
    select_profile,
)


def profile_results() -> tuple[ProfileResult, ...]:
    return (
        ProfileResult("DENSER-P1", 900, 0.01, True),
        ProfileResult("DENSER-P2", 700, 0.08, False),
        ProfileResult("DENSER-P3", 800, 0.04, True),
        ProfileResult("DENSER-P4", 800, 0.09, True),
    )


def test_selection_uses_only_passing_profiles_and_frozen_tiebreakers() -> None:
    selected = select_profile(profile_results(), SelectionRule())
    assert selected.profile_id == "DENSER-P3"
    assert selected.reason == "lowest_complete_bytes_then_lower_fallback_fraction"


def test_audit_only_metrics_cannot_select_profile() -> None:
    assert "audit_results" not in inspect.signature(select_profile).parameters


def test_no_passing_profile_freezes_safest_for_negative_evaluation() -> None:
    rows = (
        ProfileResult("DENSER-P1", 500, 0.2, False),
        ProfileResult("DENSER-P2", 600, 0.1, False),
    )
    selected = select_profile(rows, SelectionRule())
    assert selected.profile_id == "DENSER-P2"
    assert selected.operational_fallback == "standard-portfolio"
    assert selected.classification == "negative_evaluation"
