from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time

import openslide

from denser.codecs.registry import build_default_registry
from denser.codecs.source_segments import build_source_segment_candidate_from_svs
from denser.codecs.standard import build_standard_candidates, ladder_from_profile_ids
from denser.data.private_cohort import bind_verified_partition_sources
from denser.evidence.calibrate import (
    acceptance_contract_from_calibration,
    calibration_record_from_dict,
)
from denser.evidence.localized import LocalizedAcceptanceVerifier
from denser.experiments.candidate_selection import prepare_candidate_selection
from denser.governance.run_layout import RunLayout

from measure_private_feasibility import (
    _PeakContainerRss,
    _atomic_write,
    _measure_selection,
    _physical_grid,
    _sample_tiles,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure private final-style tile-worker scaling"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--codec-subprocesses", type=int, default=2)
    parser.add_argument("--tiles-per-slide", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260808)
    arguments = parser.parse_args()
    if not 3 <= arguments.workers <= 6:
        raise ValueError("parallel scaling workers must be between three and six")
    if not 1 <= arguments.codec_subprocesses <= 2:
        raise ValueError("codec subprocesses must be one or two")
    if arguments.tiles_per_slide < 2 or arguments.repeats < 2:
        raise ValueError("scaling requires at least two tiles per slide and two repeats")

    layout = RunLayout(arguments.repo_root, arguments.run_root)
    manifest_path = layout.resolve(
        "manifests", f"generation-{arguments.generation}-selected-sources.private.json"
    )
    sources = bind_verified_partition_sources(
        manifest_path,
        layout,
        "development",
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
        raise RuntimeError("parallel scaling requires calibrated HE-V1")
    calibration = calibration_record_from_dict(calibration_document["calibration"])
    contract = acceptance_contract_from_calibration(calibration)
    routing_path = layout.resolve(
        "manifests", f"generation-{arguments.generation}-standard-routing.private.json"
    )
    routing_bytes = routing_path.read_bytes()
    routes = json.loads(routing_bytes)["routes"]

    work_items = []
    for slide_ordinal, source in enumerate(sources):
        slide = openslide.OpenSlide(str(source.path))
        try:
            grid = _physical_grid(slide)
            sampled = _sample_tiles(
                slide,
                arguments.tiles_per_slide,
                seed=arguments.seed,
                slide_ordinal=slide_ordinal,
            )
        finally:
            slide.close()
        ladder = ladder_from_profile_ids(
            tuple(str(value) for value in routes[source.record.project_id])
        )
        work_items.extend(
            (source.path, address, rgb, grid, ladder) for address, rgb in sampled
        )
    if len(work_items) < 8:
        raise RuntimeError("parallel scaling requires at least eight real tiles")

    registry = build_default_registry()
    codec_slots = threading.Semaphore(arguments.codec_subprocesses)

    def encode(item):  # type: ignore[no-untyped-def]
        source_path, address, rgb, grid, ladder = item
        cell_size_px = max(1, round(8.0 / grid.mean_mpp))
        verifier = LocalizedAcceptanceVerifier(
            contract, cell_size_px, grid
        ).prepare(rgb)
        prepared = prepare_candidate_selection(
            rgb,
            contract,
            grid,
            cell_size_px=cell_size_px,
            prepared_verifier=verifier,
        )
        with codec_slots:
            standard_candidates = build_standard_candidates(rgb, ladder)
        standard, _seconds = _measure_selection(
            rgb,
            standard_candidates,
            registry,
            contract,
            grid,
            verifier,
            prepared,
            candidate_workers=1,
        )
        source_candidate = build_source_segment_candidate_from_svs(source_path, address)
        denser, _seconds = _measure_selection(
            rgb,
            [source_candidate],
            registry,
            contract,
            grid,
            verifier,
            prepared,
            incumbent=standard,
            candidate_workers=1,
        )
        return standard.packet, denser.packet

    encode(work_items[0])
    serial_seconds = []
    parallel_seconds = []
    reference_packets = None
    with _PeakContainerRss() as memory:
        for _repeat in range(arguments.repeats):
            started = time.perf_counter()
            packets = [encode(item) for item in work_items]
            serial_seconds.append(time.perf_counter() - started)
            if reference_packets is None:
                reference_packets = packets
            elif packets != reference_packets:
                raise RuntimeError("serial scaling packets are nondeterministic")
        for _repeat in range(arguments.repeats):
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
                packets = list(pool.map(encode, work_items))
            parallel_seconds.append(time.perf_counter() - started)
            if packets != reference_packets:
                raise RuntimeError("parallel scaling changed encoded packets")

    conservative_serial = min(serial_seconds)
    conservative_parallel = max(parallel_seconds)
    speedup = conservative_serial / conservative_parallel
    if speedup <= 1:
        raise RuntimeError("parallel scaling did not improve throughput")
    identity = {
        "version": "DENSER-private-parallel-scaling-1",
        "generation": arguments.generation,
        "code_commit": arguments.code_commit,
        "image_digest": arguments.image_digest,
        "calibration_digest": calibration.sha256,
        "routing_digest": hashlib.sha256(routing_bytes).hexdigest(),
        "sampling_seed": arguments.seed,
        "workers": arguments.workers,
        "codec_subprocesses": arguments.codec_subprocesses,
        "benchmark_tiles": len(work_items),
        "repeats": arguments.repeats,
    }
    report = {
        **identity,
        "serial_seconds": serial_seconds,
        "parallel_seconds": parallel_seconds,
        "measured_parallel_speedup": speedup,
        "parallel_effective_tile_seconds": conservative_parallel / len(work_items),
        "peak_container_rss_bytes": memory.peak_bytes,
        "packets_equal": True,
        "source_data_processed": True,
    }
    output = layout.resolve(
        "results",
        "development",
        f"generation-{arguments.generation}",
        f"parallel-scaling-w{arguments.workers}.private.json",
    )
    _atomic_write(output, report)
    print(
        json.dumps(
            {
                "benchmark_tiles": len(work_items),
                "measured_parallel_speedup": speedup,
                "packets_equal": True,
                "peak_container_rss_bytes": memory.peak_bytes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
