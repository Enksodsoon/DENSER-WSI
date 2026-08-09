from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time

import numpy as np

from denser.codecs.registry import build_default_registry
from denser.codecs.source_segments import build_source_segment_candidate_from_svs
from denser.codecs.standard import (
    StandardLadder,
    build_standard_candidates,
    ladder_from_profile_ids,
)
from denser.core.canonical import canonical_json_bytes
from denser.core.models import TileAddress
from denser.data.private_cohort import bind_verified_partition_sources
from denser.evidence.calibrate import (
    acceptance_contract_from_calibration,
    calibration_record_from_dict,
)
from denser.evidence.localized import (
    LocalizedAcceptanceVerifier,
    PreparedLocalizedAcceptanceVerifier,
)
from denser.evidence.types import PhysicalGrid
from denser.experiments.candidate_selection import (
    AcceptedTileCandidate,
    PreparedCandidateSelection,
    decode_and_verify_tile_packet,
    prepare_candidate_selection,
    select_smallest_accepted_candidate,
)
from denser.governance.run_layout import RunLayout
from denser.orchestration.breakthrough import FeasibilityEvidence, evaluate_generation_gate
from denser.orchestration.runtime_projection import (
    DevelopmentTimingSample,
    deterministic_sample_indices,
    project_confirmatory_runtime,
)
from denser.wsi.metadata import resolve_mpp_in_band


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
    mpp = resolve_mpp_in_band(properties, minimum=0.20, maximum=0.30)
    return PhysicalGrid(mpp, mpp)


def _sample_tiles(
    slide: object, count: int, *, seed: int, slide_ordinal: int
) -> list[tuple[TileAddress, np.ndarray]]:
    width, height = slide.dimensions  # type: ignore[attr-defined]
    size = 512
    columns = math.ceil(width / size)
    rows = math.ceil(height / size)
    indices = deterministic_sample_indices(
        columns * rows, count, seed=seed, slide_ordinal=slide_ordinal
    )
    sampled = []
    for index in indices:
        tile_y, tile_x = divmod(index, columns)
        x, y = tile_x * size, tile_y * size
        tile_width = min(size, width - x)
        tile_height = min(size, height - y)
        address = TileAddress(0, x, y, tile_width, tile_height)
        sampled.append(
            (
                address,
                np.asarray(
                    slide.read_region((x, y), 0, (tile_width, tile_height)).convert("RGB"),  # type: ignore[attr-defined]
                    dtype=np.uint8,
                ),
            )
        )
    return sampled


def _measure_selection(
    source: np.ndarray,
    candidates: list,
    registry: object,
    contract: object,
    grid: PhysicalGrid,
    prepared_verifier: PreparedLocalizedAcceptanceVerifier,
    prepared_selection: PreparedCandidateSelection,
    incumbent: AcceptedTileCandidate | None = None,
    candidate_workers: int = 1,
) -> tuple[AcceptedTileCandidate, float]:
    started = time.perf_counter()
    selected = select_smallest_accepted_candidate(
        source,
        candidates,
        registry,  # type: ignore[arg-type]
        contract,  # type: ignore[arg-type]
        grid,
        cell_size_px=max(1, round(8.0 / grid.mean_mpp)),
        prepared_verifier=prepared_verifier,
        prepared_selection=prepared_selection,
        incumbent=incumbent,
        max_candidate_workers=candidate_workers,
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
    parser.add_argument("--tiles-per-slide", type=int, default=8)
    parser.add_argument(
        "--partition", choices=("development", "pilot", "tuning"), default="development"
    )
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--worker-count", type=int, default=2)
    parser.add_argument("--candidate-workers", type=int, default=6)
    parser.add_argument("--use-standard-routing", action="store_true")
    parser.add_argument("--exclude-missing-scale", action="store_true")
    parser.add_argument("--host-reserve-bytes", type=int, required=True)
    parser.add_argument("--preflight-free-disk-bytes", type=int, required=True)
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--manifest", type=Path)
    arguments = parser.parse_args()
    if arguments.tiles_per_slide <= 0:
        raise ValueError("sampling counts must be positive")
    if arguments.generation <= 0:
        raise ValueError("generation must be positive")
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    manifest_path = arguments.manifest or layout.resolve(
        "manifests",
        "selected-sources.private.json"
        if arguments.generation == 1
        else f"generation-{arguments.generation}-selected-sources.private.json",
    )
    routing: dict[str, tuple[str, ...]] | None = None
    routing_digest = "full-standard-ladder"
    if arguments.use_standard_routing:
        routing_path = layout.resolve(
            "manifests", f"generation-{arguments.generation}-standard-routing.private.json"
        )
        routing_bytes = routing_path.read_bytes()
        routing_document = json.loads(routing_bytes)
        if routing_document.get("version") != "DENSER-standard-routing-1":
            raise ValueError("private standard routing version is invalid")
        route_values = routing_document.get("routes")
        if not isinstance(route_values, dict):
            raise ValueError("private standard routing has no routes")
        routing = {
            str(project): tuple(str(profile) for profile in profiles)
            for project, profiles in route_values.items()
            if isinstance(profiles, list)
        }
        if len(routing) != len(route_values):
            raise ValueError("private standard routing contains an invalid route")
        for profiles in routing.values():
            ladder_from_profile_ids(profiles)
        routing_digest = hashlib.sha256(routing_bytes).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    final_rows = [row for row in manifest["rows"] if row["partition"] == "final"]
    if arguments.partition == "development" and len(final_rows) < 18:
        raise RuntimeError("reduced development and final cohorts are incomplete")
    partition_sources = bind_verified_partition_sources(
        manifest_path,
        layout,
        arguments.partition,
        expected_count=6,
        generation=arguments.generation,
    )
    calibration_document = json.loads(
        layout.resolve(
            "results",
            "development",
            f"generation-{arguments.generation}",
            "calibration-record.json",
        ).read_text(encoding="utf-8")
    )
    if calibration_document["harmful_control_audit"]["status"] != "calibrated":
        raise RuntimeError("feasibility measurement requires a passing HE-V1 audit")
    calibration = calibration_record_from_dict(calibration_document["calibration"])
    contract = acceptance_contract_from_calibration(calibration)
    parallel_scaling = None
    parallel_scaling_digest = "not-required"
    if arguments.worker_count > 2:
        scaling_path = layout.resolve(
            "results",
            "development",
            f"generation-{arguments.generation}",
            f"parallel-scaling-w{arguments.worker_count}.private.json",
        )
        scaling_bytes = scaling_path.read_bytes()
        parallel_scaling = json.loads(scaling_bytes)
        parallel_scaling_digest = hashlib.sha256(scaling_bytes).hexdigest()
        expected_scaling = {
            "version": "DENSER-private-parallel-scaling-1",
            "generation": arguments.generation,
            "code_commit": arguments.code_commit,
            "image_digest": arguments.image_digest,
            "calibration_digest": calibration.sha256,
            "routing_digest": routing_digest,
            "workers": arguments.worker_count,
            "codec_subprocesses": 2,
            "candidate_workers": arguments.candidate_workers,
            "packets_equal": True,
            "source_data_processed": True,
        }
        if any(parallel_scaling.get(key) != value for key, value in expected_scaling.items()):
            raise RuntimeError("parallel scaling evidence does not match the runtime")
        if int(parallel_scaling.get("benchmark_tiles", 0)) < 8:
            raise RuntimeError("parallel scaling evidence has too few tiles")
        if int(parallel_scaling.get("project_batches", 0)) < 6:
            raise RuntimeError("parallel scaling evidence has too few project batches")
    output = layout.resolve(
        "results",
        arguments.partition,
        f"generation-{arguments.generation}",
        f"feasibility-{arguments.partition}-source-extension-primary-band-{arguments.tiles_per_slide}-w{arguments.candidate_workers}-{'route-' + routing_digest[:12] if routing else 'full'}-{'scale-filtered' if arguments.exclude_missing_scale else 'strict'}.private.json",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    identity = {
        "version": "DENSER-private-feasibility-source-extension-3-primary-mpp-band",
        "generation": arguments.generation,
        "code_commit": arguments.code_commit,
        "image_digest": arguments.image_digest,
        "calibration_digest": calibration.sha256,
        "sampling_design": "sha256-uniform-level0-without-replacement-v1",
        "sampling_seed": arguments.seed,
        "tiles_per_slide": arguments.tiles_per_slide,
        "candidate_workers": arguments.candidate_workers,
        "parallel_scaling_digest": parallel_scaling_digest,
        "standard_routing_digest": routing_digest,
        "partition": arguments.partition,
        "exclude_missing_scale": arguments.exclude_missing_scale,
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
    registry = build_default_registry()
    import openslide

    with _PeakContainerRss() as memory:
        for slide_index, source in enumerate(partition_sources):
            row = source.record
            slide = openslide.OpenSlide(str(source.path))
            try:
                try:
                    grid = _physical_grid(slide)
                except ValueError:
                    if not arguments.exclude_missing_scale:
                        raise
                    exclusions = document.setdefault("metadata_exclusions", [])
                    if not isinstance(exclusions, list):
                        raise ValueError("metadata exclusion checkpoint is invalid")
                    exclusion = {
                        "slide_index": slide_index,
                        "reason_code": "physical_scale_missing_or_outside_primary_band",
                        "outcome_inspected": False,
                    }
                    if exclusion not in exclusions:
                        exclusions.append(exclusion)
                    _atomic_write(output, document)
                    continue
                width, height = slide.dimensions
                tile_count = math.ceil(width / 512) * math.ceil(height / 512)
                tiles = _sample_tiles(
                    slide,
                    arguments.tiles_per_slide,
                    seed=arguments.seed,
                    slide_ordinal=slide_index,
                )
                for tile_index, (address, rgb) in enumerate(tiles):
                    if (slide_index, tile_index) in completed:
                        continue
                    total_started = time.perf_counter()
                    prepared_verifier = LocalizedAcceptanceVerifier(
                        contract,
                        max(1, round(8.0 / grid.mean_mpp)),
                        grid,
                    ).prepare(rgb)
                    prepared_selection = prepare_candidate_selection(
                        rgb,
                        contract,
                        grid,
                        cell_size_px=max(1, round(8.0 / grid.mean_mpp)),
                        prepared_verifier=prepared_verifier,
                    )
                    started = time.perf_counter()
                    standard_ladder = (
                        ladder_from_profile_ids(routing[row.project_id])
                        if routing is not None and row.project_id in routing
                        else StandardLadder()
                    )
                    if routing is not None and row.project_id not in routing:
                        raise ValueError("private standard routing is missing a project")
                    standard_candidates = build_standard_candidates(rgb, standard_ladder)
                    standard_build = time.perf_counter() - started
                    standard, standard_select = _measure_selection(
                        rgb,
                        standard_candidates,
                        registry,
                        contract,
                        grid,
                        prepared_verifier,
                        prepared_selection,
                        candidate_workers=arguments.candidate_workers,
                    )
                    started = time.perf_counter()
                    source_candidates = [
                        build_source_segment_candidate_from_svs(source.path, address)
                    ]
                    source_build = time.perf_counter() - started
                    source_selected, source_select = _measure_selection(
                        rgb,
                        source_candidates,
                        registry,
                        contract,
                        grid,
                        prepared_verifier,
                        prepared_selection,
                        incumbent=standard,
                    )
                    denser = source_selected
                    denser_build = standard_build + source_build
                    denser_select = standard_select + source_select
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
                            "project": row.project_id,
                            "source_bytes": row.file_size,
                            "level0_tiles": tile_count,
                            "tile_pipeline_seconds": tile_pipeline_seconds,
                            "standard": {
                                "candidate_count": len(standard_candidates),
                                "build_seconds": standard_build,
                                "select_seconds": standard_select,
                                "complete_bytes": standard.breakdown.complete,
                                "status": standard.status,
                                "profile": standard.candidate.profile_id,
                                "decode_cold_seconds": standard_cold,
                                "decode_warm_seconds": standard_warm,
                                "rejected_profiles": len(standard.rejected_profiles),
                            },
                            "denser": {
                                "candidate_count": len(standard_candidates)
                                + len(source_candidates),
                                "build_seconds": denser_build,
                                "select_seconds": denser_select,
                                "complete_bytes": denser.breakdown.complete,
                                "status": denser.status,
                                "profile": denser.candidate.profile_id,
                                "decode_cold_seconds": denser_cold,
                                "decode_warm_seconds": denser_warm,
                                "rejected_profiles": len(denser.rejected_profiles),
                            },
                        }
                    )
                    document["peak_container_rss_bytes"] = memory.peak_bytes
                    _atomic_write(output, document)
            finally:
                slide.close()
    timing_samples = []
    for slide_index, source in enumerate(partition_sources):
        slide_rows = [sample for sample in samples if int(sample["slide_index"]) == slide_index]
        if not slide_rows:
            continue
        first = slide_rows[0]
        timing_samples.append(
            DevelopmentTimingSample(
                f"slide-{slide_index}",
                source.record.project_id,
                int(first["source_bytes"]),
                int(first["level0_tiles"]),
                tuple(float(sample["tile_pipeline_seconds"]) for sample in slide_rows),
            )
        )
    free_disk = os.statvfs(arguments.run_root).f_bavail * os.statvfs(arguments.run_root).f_frsize
    gate = None
    if arguments.partition == "development":
        projection = project_confirmatory_runtime(
            timing_samples,
            final_source_bytes=sum(int(row["file_size"]) for row in final_rows),
            final_source_bytes_by_project=(
                {
                    project: sum(
                        int(row["file_size"])
                        for row in final_rows
                        if row["project_id"] == project
                    )
                    for project in sorted({str(row["project_id"]) for row in final_rows})
                }
                if parallel_scaling is not None
                else None
            ),
            worker_count=arguments.worker_count,
            measured_parallel_speedup=(
                float(parallel_scaling["measured_parallel_speedup"])
                if parallel_scaling is not None
                else None
            ),
            measured_parallel_tile_seconds=(
                float(parallel_scaling["parallel_effective_tile_seconds"])
                if parallel_scaling is not None
                else None
            ),
            measured_parallel_tile_seconds_by_project=(
                {
                    str(project): float(seconds)
                    for project, seconds in parallel_scaling[
                        "project_parallel_effective_tile_seconds"
                    ].items()
                }
                if parallel_scaling is not None
                else None
            ),
            parallel_benchmark_tiles=(
                int(parallel_scaling["benchmark_tiles"])
                if parallel_scaling is not None
                else 0
            ),
        )
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
    document["phase_classification"] = (
        "not_evaluable"
        if document.get("metadata_exclusions")
        else "evaluable"
    )
    _atomic_write(output, document)
    print(
        json.dumps(
            {
                "sampled_slides": len(timing_samples),
                "partition": arguments.partition,
                "sampled_tiles": len(samples),
                "gate_passed": gate.passed if gate is not None else None,
                "failure_codes": gate.failure_codes if gate is not None else (),
                "phase_classification": document["phase_classification"],
            },
            sort_keys=True,
        )
    )
    return 0 if gate is None or gate.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
