from __future__ import annotations

import hashlib
from collections import Counter
from statistics import median
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


def derive_bounded_development_winner_routes(
    report: dict[str, Any],
    *,
    max_profiles: int,
    expected_projects: int = 6,
    tiles_per_project: int = 8,
) -> dict[str, Any]:
    if max_profiles <= 0:
        raise ValueError("bounded routing requires a positive profile limit")
    routing = derive_development_winner_routes(
        report,
        expected_projects=expected_projects,
        tiles_per_project=tiles_per_project,
    )
    counts: dict[str, Counter[str]] = {
        project: Counter() for project in routing["routes"]
    }
    for sample in report["samples"]:
        profile = sample["standard"]["profile"]
        if profile != _FALLBACK_PROFILE:
            counts[sample["project"]][profile] += 1
    routing["routes"] = {
        project: [
            profile
            for profile, _count in sorted(
                counts[project].items(), key=lambda item: (-item[1], item[0])
            )[:max_profiles]
        ]
        for project in sorted(counts)
    }
    routing["selection_rule"] = "development-project-top-win-frequency-v1"
    routing["max_profiles_per_project"] = max_profiles
    return routing


def derive_selectively_bounded_development_winner_routes(
    report: dict[str, Any],
    project_profile_limits: dict[str, int],
    *,
    expected_projects: int = 6,
    tiles_per_project: int = 8,
) -> dict[str, Any]:
    routing = derive_development_winner_routes(
        report,
        expected_projects=expected_projects,
        tiles_per_project=tiles_per_project,
    )
    unknown = sorted(set(project_profile_limits) - set(routing["routes"]))
    if unknown:
        raise ValueError("selective routing contains an unknown project")
    if any(limit <= 0 for limit in project_profile_limits.values()):
        raise ValueError("selective routing requires positive profile limits")
    counts: dict[str, Counter[str]] = {
        project: Counter() for project in routing["routes"]
    }
    for sample in report["samples"]:
        profile = sample["standard"]["profile"]
        if profile != _FALLBACK_PROFILE:
            counts[sample["project"]][profile] += 1
    for project, limit in sorted(project_profile_limits.items()):
        routing["routes"][project] = [
            profile
            for profile, _count in sorted(
                counts[project].items(), key=lambda item: (-item[1], item[0])
            )[:limit]
        ]
    for profiles in routing["routes"].values():
        ladder_from_profile_ids(tuple(profiles))
    routing["selection_rule"] = "development-project-selective-win-frequency-v1"
    routing["project_profile_limits"] = dict(sorted(project_profile_limits.items()))
    return routing


def evaluate_development_route_fairness(
    full_report: dict[str, Any],
    routed_report: dict[str, Any],
    *,
    maximum_median_ratio: float = 1.01,
    maximum_tile_ratio: float = 1.10,
    minimum_exact_fraction: float = 0.90,
) -> dict[str, Any]:
    if full_report.get("standard_routing_digest") != "full-standard-ladder":
        raise ValueError("fairness evaluation requires a full standard ladder reference")
    if routed_report.get("standard_routing_digest") in {None, "full-standard-ladder"}:
        raise ValueError("fairness evaluation requires a routed development report")
    if full_report.get("partition") != "development" or routed_report.get("partition") != "development":
        raise ValueError("fairness evaluation is development-only")

    def rows_by_key(report: dict[str, Any]) -> dict[tuple[str, int, int], int]:
        rows: dict[tuple[str, int, int], int] = {}
        for sample in report.get("samples", []):
            key = (
                str(sample["project"]),
                int(sample["slide_index"]),
                int(sample["tile_index"]),
            )
            complete_bytes = int(sample["standard"]["complete_bytes"])
            if key in rows or complete_bytes <= 0:
                raise ValueError("fairness evidence contains invalid or duplicate rows")
            rows[key] = complete_bytes
        return rows

    full = rows_by_key(full_report)
    routed = rows_by_key(routed_report)
    if not full or full.keys() != routed.keys():
        raise ValueError("fairness evidence does not cover identical development tiles")
    ratios = [routed[key] / full[key] for key in sorted(full)]
    median_ratio = float(median(ratios))
    maximum_ratio = max(ratios)
    exact_fraction = sum(routed[key] == full[key] for key in full) / len(full)
    failures = []
    if median_ratio > maximum_median_ratio:
        failures.append("median_complete_byte_ratio_exceeded")
    if maximum_ratio > maximum_tile_ratio:
        failures.append("maximum_complete_byte_ratio_exceeded")
    if exact_fraction < minimum_exact_fraction:
        failures.append("exact_match_fraction_below_minimum")
    return {
        "version": "DENSER-development-route-fairness-1",
        "development_tiles": len(full),
        "median_complete_byte_ratio": median_ratio,
        "maximum_complete_byte_ratio": maximum_ratio,
        "exact_fraction": exact_fraction,
        "thresholds": {
            "maximum_median_ratio": maximum_median_ratio,
            "maximum_tile_ratio": maximum_tile_ratio,
            "minimum_exact_fraction": minimum_exact_fraction,
        },
        "failure_codes": failures,
        "passed": not failures,
    }
