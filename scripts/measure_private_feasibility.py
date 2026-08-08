from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import threading
import time

import numpy as np

from denser.codecs.quadtree import build_jpegxl_quadtree_candidates
from denser.codecs.registry import build_default_registry
from denser.codecs.standard import StandardLadder, build_standard_candidates
from denser.core.canonical import canonical_json_bytes
from denser.evidence.calibrate import (
    acceptance_contract_from_calibration,
    calibration_record_from_dict,
)
from denser.evidence.types import PhysicalGrid
from denser.experiments.candidate_selection import (
    AcceptedTileCandidate,
    decode_and_verify_tile_packet,
    select_smallest_accepted_candidate,
)
from denser.governance.run_layout import RunLayout
from denser.method.candidates import (
    CandidateProfile,
    build_denser_candidates,
    build_uniform_candidates,
)
from denser.orchestration.breakthrough import FeasibilityEvidence, evaluate_generation_gate
from denser.orchestration.runtime_projection import (
    DevelopmentTimingSample,
    project_confirmatory_runtime,
)


class _PeakContainerRss(AbstractContextManager["_PeakContainerRss"]):
    def __init__(self) -> None:
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    @staticmethod
    def _rss_bytes() -> int:
        total_kib = 0
        for status in Path("/proc").glob("[0-9]*/status"):
            try:
                for line in status.read_text(encoding="ascii").splitlines():
                    if line.startswith("VmRSS:"):
                        total_kib += int(line.split()[1])
                        break
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
        return total_kib * 1024

    def _watch(self) -> None:
        while not self._stop.wait(0.05):
            self.peak_bytes = max(self.peak_bytes, self._rss_bytes())

    def __enter__(self) -> "_PeakContainerRss":
        self.peak_bytes = self._rss_bytes()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self.peak_bytes = max(self.peak_bytes, self._rss_bytes())


def _physical_grid(slide: object) -> PhysicalGrid:
    properties = slide.properties  # type: ignore[attr-defined]
    shared = properties.get("aperio.MPP")
    mpp_x = properties.get("openslide.mpp-x", shared)
    mpp_y = properties.get("openslide.mpp-y", shared)
    if mpp_x is None or mpp_y is None:
        raise ValueError("development slide lacks physical-scale metadata")
    grid = PhysicalGrid(float(mpp_x), float(mpp_y))
    if not (0.1 <= grid.mpp_x <= 1.0 and 0.1 <= grid.mpp_y <= 1.0):
        raise ValueError("development slide physical scale is outside frozen range")
    return grid


def _sample_tiles(slide: object, count: int, search_grid: int) -> list[np.ndarray]:
    width, height = slide.dimensions  # type: ignore[attr-defined]
    size = 512
    candidates: list[tuple[float, int, int, np.ndarray]] = []
    for y in np.linspace(0, max(0, height - size), search_grid, dtype=int):
        for x in np.linspace(0, max(0, width - size), search_grid, dtype=int):
            rgb = np.asarray(
                slide.read_region((int(x), int(y)), 0, (size, size)).convert("RGB"),  # type: ignore[attr-defined]
                dtype=np.uint8,
            )
            intensity = rgb.astype(np.float64).mean(axis=2)
            tissue = float(np.mean((intensity < 240) & (intensity > 20)))
            candidates.append((tissue, int(y), int(x), rgb))
    candidates.sort(key=lambda row: (-row[0], row[1], row[2]))
    if len(candidates) < count:
        raise RuntimeError("development slide does not contain enough benchmark candidates")
    return [row[3] for row in candidates[:count]]


def _sensitivity(rgb: np.ndarray) -> np.ndarray:
    values = rgb.astype(np.float64)
    sensitivity = np.empty_like(values)
    for channel in range(3):
        gy, gx = np.gradient(values[:, :, channel])
        sensitivity[:, :, channel] = np.hypot(gx, gy) + 1.0
    return sensitivity


def _measure_selection(
    source: np.ndarray,
    candidates: list,
    registry: object,
    contract: object,
    grid: PhysicalGrid,
) -> tuple[AcceptedTileCandidate, float]:
    started = time.perf_counter()
    selected = select_smallest_accepted_candidate(
        source,
        candidates,
        registry,  # type: ignore[arg-type]
        contract,  # type: ignore[arg-type]
        grid,
        cell_size_px=max(1, round(8.0 / grid.mean_mpp)),
    )
    return selected, time.perf_counter() - started


def _decode_seconds(
    selected: AcceptedTileCandidate,
    shape: tuple[int, int, int],
    registry: object,
    contract: object,
) -> tuple[float, float]:
    started = time.perf_counter()
    decode_and_verify_tile_packet(selected.packet, shape, registry, contract)  # type: ignore[arg-type]
    cold = time.perf_counter() - started
    warm_values = []
    for _index in range(3):
        started = time.perf_counter()
        decode_and_verify_tile_packet(selected.packet, shape, registry, contract)  # type: ignore[arg-type]
        warm_values.append(time.perf_counter() - started)
    return cold, float(np.median(warm_values))


def _atomic_write(path: Path, document: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(document) + b"\n")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Private bounded real-tile feasibility measurement")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--tiles-per-slide", type=int, default=3)
    parser.add_argument("--search-grid", type=int, default=5)
    parser.add_argument("--worker-count", type=int, default=2)
    parser.add_argument("--host-reserve-bytes", type=int, required=True)
    parser.add_argument("--preflight-free-disk-bytes", type=int, required=True)
    arguments = parser.parse_args()
    if arguments.tiles_per_slide <= 0 or arguments.search_grid <= 0:
        raise ValueError("sampling counts must be positive")
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    manifest = json.loads(
        layout.resolve("manifests", "selected-sources.private.json").read_text(encoding="utf-8")
    )
    development_rows = [row for row in manifest["rows"] if row["partition"] == "development"]
    final_rows = [row for row in manifest["rows"] if row["partition"] == "final"]
    if len(development_rows) < 6 or len(final_rows) < 18:
        raise RuntimeError("reduced development and final cohorts are incomplete")
    calibration_document = json.loads(
        layout.resolve(
            "results", "development", "generation-1", "calibration-record.json"
        ).read_text(encoding="utf-8")
    )
    if calibration_document["harmful_control_audit"]["status"] != "calibrated":
        raise RuntimeError("feasibility measurement requires a passing HE-V1 audit")
    calibration = calibration_record_from_dict(calibration_document["calibration"])
    contract = acceptance_contract_from_calibration(calibration)
    output = layout.resolve(
        "results", "development", "generation-1", "feasibility-measurement.private.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    identity = {
        "version": "DENSER-private-feasibility-1",
        "code_commit": arguments.code_commit,
        "image_digest": arguments.image_digest,
        "calibration_digest": calibration.sha256,
    }
    document: dict[str, object] = {**identity, "samples": []}
    if output.exists():
        document = json.loads(output.read_text(encoding="utf-8"))
        if any(document.get(key) != value for key, value in identity.items()):
            raise RuntimeError("existing feasibility checkpoint belongs to a different frozen runtime")
    samples = document["samples"]
    if not isinstance(samples, list):
        raise ValueError("feasibility checkpoint sample list is invalid")
    completed = {
        (int(row["slide_index"]), int(row["tile_index"])) for row in samples
    }
    profile = CandidateProfile((1.0, 2.0, 4.0))
    registry = build_default_registry()
    import openslide

    with _PeakContainerRss() as memory:
        for slide_index, row in enumerate(development_rows):
            source = layout.resolve("sources", "development", row["file_name"])
            if not source.is_file() or source.stat().st_size != int(row["file_size"]):
                raise RuntimeError("all six verified development sources are required")
            slide = openslide.OpenSlide(str(source))
            try:
                grid = _physical_grid(slide)
                width, height = slide.dimensions
                tile_count = math.ceil(width / 512) * math.ceil(height / 512)
                tiles = _sample_tiles(slide, arguments.tiles_per_slide, arguments.search_grid)
                for tile_index, rgb in enumerate(tiles):
                    if (slide_index, tile_index) in completed:
                        continue
                    total_started = time.perf_counter()
                    started = time.perf_counter()
                    standard_candidates = build_standard_candidates(rgb, StandardLadder())
                    standard_build = time.perf_counter() - started
                    standard, standard_select = _measure_selection(
                        rgb, standard_candidates, registry, contract, grid
                    )
                    started = time.perf_counter()
                    uniform_candidates = build_uniform_candidates(rgb, profile)
                    uniform_build = time.perf_counter() - started
                    uniform, uniform_select = _measure_selection(
                        rgb, uniform_candidates, registry, contract, grid
                    )
                    started = time.perf_counter()
                    sensitivity = _sensitivity(rgb)
                    denser_candidates = build_denser_candidates(rgb, sensitivity, profile)
                    denser_candidates.extend(build_jpegxl_quadtree_candidates(rgb, sensitivity))
                    denser_build = time.perf_counter() - started
                    denser, denser_select = _measure_selection(
                        rgb, denser_candidates, registry, contract, grid
                    )
                    tile_pipeline_seconds = time.perf_counter() - total_started
                    standard_cold, standard_warm = _decode_seconds(
                        standard, rgb.shape, registry, contract
                    )
                    denser_cold, denser_warm = _decode_seconds(
                        denser, rgb.shape, registry, contract
                    )
                    samples.append(
                        {
                            "slide_index": slide_index,
                            "tile_index": tile_index,
                            "project": row["project_id"],
                            "source_bytes": int(row["file_size"]),
                            "level0_tiles": tile_count,
                            "tile_pipeline_seconds": tile_pipeline_seconds,
                            "standard": {
                                "build_seconds": standard_build,
                                "select_seconds": standard_select,
                                "complete_bytes": standard.breakdown.complete,
                                "status": standard.status,
                                "decode_cold_seconds": standard_cold,
                                "decode_warm_seconds": standard_warm,
                            },
                            "uniform": {
                                "build_seconds": uniform_build,
                                "select_seconds": uniform_select,
                                "complete_bytes": uniform.breakdown.complete,
                                "status": uniform.status,
                            },
                            "denser": {
                                "build_seconds": denser_build,
                                "select_seconds": denser_select,
                                "complete_bytes": denser.breakdown.complete,
                                "status": denser.status,
                                "profile": denser.candidate.profile_id,
                                "decode_cold_seconds": denser_cold,
                                "decode_warm_seconds": denser_warm,
                            },
                        }
                    )
                    document["peak_container_rss_bytes"] = memory.peak_bytes
                    _atomic_write(output, document)
            finally:
                slide.close()
    timing_samples = []
    for slide_index, row in enumerate(development_rows):
        slide_rows = [sample for sample in samples if int(sample["slide_index"]) == slide_index]
        if not slide_rows:
            continue
        first = slide_rows[0]
        timing_samples.append(
            DevelopmentTimingSample(
                f"slide-{slide_index}",
                str(row["project_id"]),
                int(first["source_bytes"]),
                int(first["level0_tiles"]),
                tuple(float(sample["tile_pipeline_seconds"]) for sample in slide_rows),
            )
        )
    projection = project_confirmatory_runtime(
        timing_samples,
        final_source_bytes=sum(int(row["file_size"]) for row in final_rows),
        worker_count=arguments.worker_count,
    )
    free_disk = os.statvfs(arguments.run_root).f_bavail * os.statvfs(arguments.run_root).f_frsize
    gate = evaluate_generation_gate(
        FeasibilityEvidence(
            projection.projected_confirmatory_seconds,
            int(document["peak_container_rss_bytes"]),
            arguments.host_reserve_bytes,
            free_disk,
            arguments.preflight_free_disk_bytes,
            len(final_rows),
            4,
        )
    )
    document["projection"] = asdict(projection)
    document["generation_gate"] = asdict(gate)
    document["source_data_processed"] = True
    _atomic_write(output, document)
    print(
        json.dumps(
            {
                "development_slides": len(timing_samples),
                "sampled_tiles": len(samples),
                "gate_passed": gate.passed,
                "failure_codes": gate.failure_codes,
            },
            sort_keys=True,
        )
    )
    return 0 if gate.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
