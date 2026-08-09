from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from denser.core.canonical import canonical_json_bytes
from denser.data.private_cohort import bind_verified_partition_sources
from denser.evidence.calibrate import (
    acceptance_contract_from_calibration,
    calibrate_contract,
    verify_calibration,
)
from denser.evidence.controls import CalibrationProfile
from denser.evidence.controls_v1 import (
    build_balanced_control_cohort,
    verify_control_configuration,
)
from denser.evidence.types import PhysicalGrid
from denser.governance.run_layout import RunLayout
from denser.wsi.metadata import MetadataError, resolve_mpp_in_band


def _mpp(slide) -> PhysicalGrid:  # type: ignore[no-untyped-def]
    mpp = resolve_mpp_in_band(slide.properties, minimum=0.20, maximum=0.30)
    return PhysicalGrid(mpp, mpp)


def _sample_tiles(path: Path, count: int, search_grid: int) -> list[tuple[np.ndarray, PhysicalGrid]]:
    import openslide

    slide = openslide.OpenSlide(str(path))
    try:
        grid = _mpp(slide)
        width, height = slide.dimensions
        size = 512
        candidates: list[tuple[float, np.ndarray, PhysicalGrid]] = []
        for y in np.linspace(0, max(0, height - size), search_grid, dtype=int):
            for x in np.linspace(0, max(0, width - size), search_grid, dtype=int):
                rgb = np.asarray(
                    slide.read_region((int(x), int(y)), 0, (size, size)).convert("RGB"),
                    dtype=np.uint8,
                )
                intensity = rgb.astype(np.float64).mean(axis=2)
                tissue = float(np.mean((intensity < 240) & (intensity > 20)))
                candidates.append((tissue, rgb, grid))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [(rgb, physical) for _score, rgb, physical in candidates[:count]]
    finally:
        slide.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Private real-tile HE-V1 calibration")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--tiles-per-slide", type=int, default=4)
    parser.add_argument("--search-grid", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--manifest", type=Path)
    arguments = parser.parse_args()
    if arguments.generation <= 0:
        raise ValueError("generation must be positive")
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    control_path = arguments.repo_root / "configs" / "experiment" / "he_v1_controls.json"
    control_document = json.loads(control_path.read_text(encoding="utf-8"))
    verify_control_configuration(control_document)
    manifest_path = arguments.manifest or layout.resolve(
        "manifests",
        "selected-sources.private.json"
        if arguments.generation == 1
        else f"generation-{arguments.generation}-selected-sources.private.json",
    )
    sources = bind_verified_partition_sources(
        manifest_path,
        layout,
        "development",
        expected_count=6,
        generation=arguments.generation,
    )
    sampled_slides: list[list[tuple[np.ndarray, str, PhysicalGrid]]] = []
    metadata_exclusions: list[dict[str, object]] = []
    for slide_index, source in enumerate(sources):
        try:
            sampled = _sample_tiles(
                source.path, arguments.tiles_per_slide, arguments.search_grid
            )
        except MetadataError:
            metadata_exclusions.append(
                {
                    "slide_index": slide_index,
                    "reason_code": "physical_scale_missing_or_outside_primary_band",
                    "outcome_inspected": False,
                }
            )
            continue
        sampled_slides.append(
            [
                (rgb, f"slide-{slide_index:02d}-tile-{tile_index:02d}", grid)
                for tile_index, (rgb, grid) in enumerate(sampled)
            ]
        )
    if not sampled_slides:
        raise RuntimeError("no development slides satisfy the primary physical-scale band")
    benign, harmful = build_balanced_control_cohort(
        sampled_slides, seed=arguments.seed
    )
    profile = CalibrationProfile(
        float(control_document["alpha"]), tuple(pair.control_id for pair in harmful)
    )
    calibration = calibrate_contract(list(benign), profile)
    audit = verify_calibration(calibration, list(harmful))
    document: dict[str, object] = {
        "version": "DENSER-private-development-calibration-2-primary-mpp-band",
        "generation": arguments.generation,
        "selected_slide_count": len(sources),
        "slide_count": len(sampled_slides),
        "phase_classification": "not_evaluable" if metadata_exclusions else "evaluable",
        "metadata_exclusions": metadata_exclusions,
        "fit_tile_count": len(benign),
        "challenge_tile_count": len(harmful),
        "calibration": asdict(calibration),
        "harmful_control_audit": asdict(audit),
    }
    if audit.status == "calibrated":
        document["acceptance_contract"] = asdict(
            acceptance_contract_from_calibration(calibration)
        )
    output = layout.resolve(
        "results",
        "development",
        f"generation-{arguments.generation}",
        "calibration-record.json",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(document) + b"\n")
    print(
        json.dumps(
            {
                "status": audit.status,
                "slides": len(sampled_slides),
                "excluded_slides": len(metadata_exclusions),
                "fit_tiles": len(benign),
                "challenge_tiles": len(harmful),
                "missed_challenges": len(audit.missed_control_ids),
            },
            sort_keys=True,
        )
    )
    return 0 if audit.status == "calibrated" else 2


if __name__ == "__main__":
    raise SystemExit(main())
