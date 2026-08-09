from __future__ import annotations

import hashlib
from typing import Any

from denser.codecs.standard import ladder_from_profile_ids
from denser.core.canonical import canonical_json_bytes


_FALLBACK_PROFILE = "fallback-v1-rct-zlib-fixed-9"


def derive_development_winner_routes(
    report: dict[str, Any],
    *,
    expected_projects: int = 6,
    tiles_per_project: int = 8,
) -> dict[str, Any]:
    if (
        report.get("partition") != "development"
        or report.get("standard_routing_digest") != "full-standard-ladder"
        or report.get("source_data_processed") is not True
        or report.get("phase_classification") != "evaluable"
    ):
        raise ValueError("routing derivation requires evaluable full standard ladder evidence")
    samples = report.get("samples")
    if not isinstance(samples, list):
        raise ValueError("full ladder evidence has no sample rows")
    winners: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("standard"), dict):
            raise ValueError("full ladder evidence contains an invalid sample")
        project = sample.get("project")
        standard = sample["standard"]
        profile = standard.get("profile")
        if (
            not isinstance(project, str)
            or not isinstance(profile, str)
            or standard.get("candidate_count") != 12
        ):
            raise ValueError("routing derivation requires all twelve standard candidates")
        counts[project] = counts.get(project, 0) + 1
        if profile != _FALLBACK_PROFILE:
            winners.setdefault(project, set()).add(profile)
        else:
            winners.setdefault(project, set())
    if len(counts) != expected_projects or any(
        count != tiles_per_project for count in counts.values()
    ):
        raise ValueError("routing derivation requires eight tiles for every project")
    routes = {project: sorted(winners[project]) for project in sorted(winners)}
    if any(not profiles for profiles in routes.values()):
        raise ValueError("each project requires at least one accepted nonfallback winner")
    for profiles in routes.values():
        ladder_from_profile_ids(tuple(profiles))
    return {
        "version": "DENSER-standard-routing-1",
        "selection_rule": "development-project-winner-union-v1",
        "development_tiles": len(samples),
        "full_ladder_report_sha256": hashlib.sha256(
            canonical_json_bytes(report)
        ).hexdigest(),
        "routes": routes,
    }
