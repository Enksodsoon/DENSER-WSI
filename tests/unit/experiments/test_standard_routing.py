from __future__ import annotations

import pytest

from denser.experiments.standard_routing import (
    derive_bounded_development_winner_routes,
    derive_development_winner_routes,
    derive_selectively_bounded_development_winner_routes,
    evaluate_development_route_fairness,
)


def _report() -> dict[str, object]:
    samples = []
    for project_index in range(6):
        project = f"PROJECT-{project_index}"
        for tile_index in range(8):
            profile = (
                "fallback-v1-rct-zlib-fixed-9"
                if tile_index == 0
                else ("jpeg2000-r4" if tile_index % 2 else "avif-q90-s6")
            )
            samples.append(
                {
                    "project": project,
                    "slide_index": project_index,
                    "tile_index": tile_index,
                    "standard": {"candidate_count": 12, "profile": profile},
                }
            )
    return {
        "partition": "development",
        "standard_routing_digest": "full-standard-ladder",
        "source_data_processed": True,
        "phase_classification": "evaluable",
        "samples": samples,
    }


def test_winner_routes_are_union_of_nonfallback_full_ladder_winners() -> None:
    routing = derive_development_winner_routes(_report())
    assert routing["version"] == "DENSER-standard-routing-1"
    assert routing["selection_rule"] == "development-project-winner-union-v1"
    assert routing["development_tiles"] == 48
    assert set(routing["routes"]) == {f"PROJECT-{index}" for index in range(6)}
    assert all(
        profiles == ["avif-q90-s6", "jpeg2000-r4"]
        for profiles in routing["routes"].values()
    )


def test_winner_routes_reject_non_full_or_incomplete_evidence() -> None:
    report = _report()
    report["standard_routing_digest"] = "routed"
    with pytest.raises(ValueError, match="full standard ladder"):
        derive_development_winner_routes(report)
    report = _report()
    report["samples"] = report["samples"][:-1]
    with pytest.raises(ValueError, match="eight tiles"):
        derive_development_winner_routes(report)


def test_bounded_routes_choose_most_frequent_winners_deterministically() -> None:
    routing = derive_bounded_development_winner_routes(_report(), max_profiles=1)
    assert routing["selection_rule"] == "development-project-top-win-frequency-v1"
    assert routing["max_profiles_per_project"] == 1
    assert all(profiles == ["jpeg2000-r4"] for profiles in routing["routes"].values())
    with pytest.raises(ValueError, match="positive profile limit"):
        derive_bounded_development_winner_routes(_report(), max_profiles=0)


def test_selective_limits_preserve_unlisted_project_winner_unions() -> None:
    routing = derive_selectively_bounded_development_winner_routes(
        _report(), {"PROJECT-0": 1}
    )
    assert routing["selection_rule"] == "development-project-selective-win-frequency-v1"
    assert routing["project_profile_limits"] == {"PROJECT-0": 1}
    assert routing["routes"]["PROJECT-0"] == ["jpeg2000-r4"]
    assert routing["routes"]["PROJECT-1"] == ["avif-q90-s6", "jpeg2000-r4"]
    with pytest.raises(ValueError, match="unknown project"):
        derive_selectively_bounded_development_winner_routes(
            _report(), {"PROJECT-unknown": 1}
        )


def test_route_fairness_gate_rejects_material_tail_inflation() -> None:
    full = _report()
    routed = _report()
    routed["standard_routing_digest"] = "bounded-route"
    for row in full["samples"]:
        row["standard"]["complete_bytes"] = 100
    for row in routed["samples"]:
        row["standard"]["complete_bytes"] = 100
    routed["samples"][0]["standard"]["complete_bytes"] = 112
    evidence = evaluate_development_route_fairness(full, routed)
    assert evidence["passed"] is False
    assert evidence["failure_codes"] == ["maximum_complete_byte_ratio_exceeded"]
    assert evidence["exact_fraction"] == pytest.approx(47 / 48)

    routed["samples"][0]["standard"]["complete_bytes"] = 108
    evidence = evaluate_development_route_fairness(full, routed)
    assert evidence["passed"] is True
    assert evidence["maximum_complete_byte_ratio"] == pytest.approx(1.08)
