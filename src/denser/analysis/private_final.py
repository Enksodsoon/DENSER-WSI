from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from denser.analysis.final_results import (
    FinalAnalysisResult,
    FinalSlideResult,
    analyze_final_results,
)
from denser.experiments.final import FinalPerformanceSummary


_CONTAINER_NAME = re.compile(r"^final-(\d{3})\.(standard|denser)\.mcv2$")


@dataclass(frozen=True, slots=True)
class PrivateFinalAnalysis:
    rows: tuple[FinalSlideResult, ...]
    analysis: FinalAnalysisResult


def analyze_private_final_documents(
    summary: dict[str, Any],
    manifest: dict[str, Any],
    routing: dict[str, Any],
    *,
    seed: int,
) -> PrivateFinalAnalysis:
    final_manifest_rows = sorted(
        (row for row in manifest.get("rows", ()) if row.get("partition") == "final"),
        key=lambda row: (row["project_id"], row["research_id"]),
    )
    if len(final_manifest_rows) != 18 or summary.get("slide_count") != 18:
        raise ValueError("private final analysis requires exactly 18 final slides")
    indexed: dict[tuple[int, str], dict[str, Any]] = {}
    for container in summary.get("containers", ()):
        match = _CONTAINER_NAME.fullmatch(Path(str(container.get("path", ""))).name)
        if match is None:
            raise ValueError("private final container name is invalid")
        key = (int(match.group(1)), match.group(2))
        if key in indexed or container.get("method") != key[1]:
            raise ValueError("private final container binding is duplicated or inconsistent")
        indexed[key] = container
    expected = {
        (ordinal, method)
        for ordinal in range(len(final_manifest_rows))
        for method in ("standard", "denser")
    }
    if set(indexed) != expected:
        raise ValueError("private final container set is incomplete")
    rows: list[FinalSlideResult] = []
    for ordinal, manifest_row in enumerate(final_manifest_rows):
        standard = indexed[(ordinal, "standard")]
        denser = indexed[(ordinal, "denser")]
        if standard.get("tile_count") != denser.get("tile_count"):
            raise ValueError("paired final containers have different tile counts")
        rows.append(
            FinalSlideResult(
                str(manifest_row["research_id"]),
                str(manifest_row["project_id"]),
                int(standard["complete_bytes"]),
                int(denser["complete_bytes"]),
                int(standard["tile_count"]),
            )
        )
    try:
        performance = FinalPerformanceSummary(**summary["performance"])
    except (KeyError, TypeError) as error:
        raise ValueError("private final performance record is invalid") from error
    routes = routing.get("routes")
    projects = {row.project for row in rows}
    if not isinstance(routes, dict) or not projects.issubset(routes):
        raise ValueError("private final routing is incomplete")
    families = {
        str(profile).split("-", 1)[0]
        for project in projects
        for profile in routes[project]
    }
    full_slide_processing = all(
        summary.get(key) is True
        for key in ("source_data_processed", "full_level0_grid", "ledgers_match_files")
    )
    analysis = analyze_final_results(
        tuple(rows),
        performance,
        standard_codec_families=len(families),
        acceptance_violations=int(summary.get("unresolved_acceptance_violations", -1)),
        independent_random_tile_decode=(
            summary.get("random_tiles_independently_decodable") is True
        ),
        full_slide_processing=full_slide_processing,
        seed=seed,
    )
    return PrivateFinalAnalysis(tuple(rows), analysis)
