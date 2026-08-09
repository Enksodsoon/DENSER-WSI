from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from denser.method.candidates import (
    CandidateProfile,
    build_denser_candidates,
    build_uniform_candidates,
    decode_candidate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark one private tile without emitting identifiers")
    parser.add_argument("slide", type=Path, nargs="?")
    parser.add_argument("--slide-root", type=Path)
    parser.add_argument("--tile-size", type=int, default=512)
    parser.add_argument("--step", type=float, default=4.0)
    parser.add_argument("--search-grid", type=int, default=5)
    parser.add_argument("--verified", action="store_true")
    parser.add_argument("--calibration", type=Path)
    arguments = parser.parse_args()
    if (arguments.slide is None) == (arguments.slide_root is None):
        parser.error("provide exactly one slide path or --slide-root")
    slide_path = arguments.slide
    if slide_path is None:
        slides = sorted(arguments.slide_root.glob("*.svs"))
        if not slides:
            raise RuntimeError("slide root contains no SVS development source")
        slide_path = slides[0]
    import openslide

    slide = openslide.OpenSlide(str(slide_path))
    width, height = slide.dimensions
    size = arguments.tile_size
    best: tuple[float, np.ndarray] | None = None
    for y in np.linspace(0, max(0, height - size), arguments.search_grid, dtype=int):
        for x in np.linspace(0, max(0, width - size), arguments.search_grid, dtype=int):
            candidate = np.asarray(slide.read_region((int(x), int(y)), 0, (size, size)).convert("RGB"))
            intensity = candidate.astype(np.float64).mean(axis=2)
            tissue_fraction = float(np.mean((intensity < 240) & (intensity > 20)))
            if best is None or tissue_fraction > best[0]:
                best = (tissue_fraction, candidate)
    if best is None:
        raise RuntimeError("no benchmark tile was available")
    tissue_fraction, rgb = best
    values = rgb.astype(np.float64)
    sensitivity = np.empty_like(values)
    for channel in range(3):
        gy, gx = np.gradient(values[:, :, channel])
        sensitivity[:, :, channel] = np.hypot(gx, gy) + 1.0
    profile = CandidateProfile((1.0, 2.0, arguments.step))
    started = time.perf_counter()
    uniform_candidates = build_uniform_candidates(rgb, profile)
    uniform = uniform_candidates[-1]
    uniform_seconds = time.perf_counter() - started
    started = time.perf_counter()
    denser_candidates = build_denser_candidates(rgb, sensitivity, profile)
    denser = denser_candidates[-1]
    denser_seconds = time.perf_counter() - started
    started = time.perf_counter()
    decoded = decode_candidate(denser.payload, denser.allocation_map)
    decode_seconds = time.perf_counter() - started
    report: dict[str, object] = {
                "allocation_bytes": len(denser.allocation_map),
                "decode_seconds": round(decode_seconds, 6),
                "decoded_shape_valid": decoded.shape == rgb.shape,
                "denser_complete_bytes": denser.complete_bytes,
                "denser_seconds": round(denser_seconds, 6),
                "uniform_complete_bytes": uniform.complete_bytes,
                "uniform_seconds": round(uniform_seconds, 6),
                "tissue_fraction": round(tissue_fraction, 6),
    }
    if arguments.verified:
        from denser.codecs.registry import build_default_registry
        from denser.codecs.quadtree import build_jpegxl_quadtree_candidate
        from denser.codecs.standard import StandardLadder, build_standard_candidates
        from denser.evidence.calibrate import (
            acceptance_contract_from_calibration,
            calibration_record_from_dict,
        )
        from denser.evidence.types import AcceptanceContract, PhysicalGrid
        from denser.experiments.candidate_selection import select_smallest_accepted_candidate
        from denser.wsi.metadata import resolve_mpp_in_band

        registry = build_default_registry()
        contract = AcceptanceContract()
        if arguments.calibration is not None:
            calibration_document = json.loads(arguments.calibration.read_text(encoding="utf-8"))
            audit = calibration_document.get("harmful_control_audit", {})
            if audit.get("status") != "calibrated":
                raise ValueError("verified benchmark requires a passing harmful-control audit")
            contract = acceptance_contract_from_calibration(
                calibration_record_from_dict(calibration_document["calibration"])
            )
        mpp = resolve_mpp_in_band(slide.properties, minimum=0.20, maximum=0.30)
        grid = PhysicalGrid(mpp, mpp)
        portfolios = {
            "standard": build_standard_candidates(rgb, StandardLadder()),
            "uniform": uniform_candidates,
            "denser": [
                *denser_candidates,
                build_jpegxl_quadtree_candidate(rgb, sensitivity),
            ],
        }
        verified: dict[str, object] = {}
        for name, candidates in portfolios.items():
            started = time.perf_counter()
            selected = select_smallest_accepted_candidate(
                rgb, candidates, registry, contract, grid, cell_size_px=32
            )
            verified[name] = {
                "complete_bytes": selected.breakdown.complete,
                "profile": selected.candidate.profile_id,
                "seconds": round(time.perf_counter() - started, 6),
                "status": selected.status,
            }
        report["verified"] = verified
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
