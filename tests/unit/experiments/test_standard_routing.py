from __future__ import annotations

import pytest

from denser.experiments.standard_routing import derive_development_winner_routes


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
