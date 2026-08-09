from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import threading
from dataclasses import asdict
from pathlib import Path

import numpy as np

from denser.codecs.source_segments import build_source_segment_candidate_from_svs
from denser.codecs.standard import ladder_from_profile_ids
from denser.core.canonical import canonical_json_bytes
from denser.data.manifest import PartitionManifest, SlideRecord
from denser.data.private_cohort import bind_verified_partition_sources
from denser.evidence.calibrate import (
    acceptance_contract_from_calibration,
    calibration_record_from_dict,
)
from denser.experiments.final import (
    FinalHoldoutConfig,
    FinalSlideInput,
    run_final_holdout,
    summarize_final_performance,
)
from denser.experiments.freeze import freeze_record_from_dict
from denser.experiments.runtime_freeze import build_runtime_freeze_context
from denser.governance.run_layout import PrivateRunLock, RunLayout
from denser.wsi.metadata import resolve_mpp_in_band


class _ThreadedSlideReader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self._handles: list[object] = []
        self._lock = threading.Lock()

    def __call__(self, address):  # type: ignore[no-untyped-def]
        import openslide

        slide = getattr(self._local, "slide", None)
        if slide is None:
            slide = openslide.OpenSlide(str(self.path))
            self._local.slide = slide
            with self._lock:
                self._handles.append(slide)
        return np.asarray(
            slide.read_region(
                (address.x, address.y), address.level, (address.width, address.height)
            ).convert("RGB"),
            dtype=np.uint8,
        )

    def close(self) -> None:
        with self._lock:
            handles, self._handles = self._handles, []
        for handle in handles:
            handle.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen private full-slide holdout")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--cpu-workers", type=int, default=2)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    context = build_runtime_freeze_context(
        arguments.repo_root,
        arguments.run_root,
        generation=arguments.generation,
        git_commit=arguments.git_commit,
        dirty_tree=False,
        container_image_digest=arguments.image_digest,
    )
    freeze_path = layout.resolve(
        "results", "final", f"generation-{arguments.generation}", "freeze-record.json"
    )
    freeze = freeze_record_from_dict(json.loads(freeze_path.read_text(encoding="utf-8")))
    manifest_path = layout.resolve(
        "manifests", f"generation-{arguments.generation}-selected-sources.private.json"
    )
    manifest_document = json.loads(manifest_path.read_text(encoding="utf-8"))
    final_rows = sorted(
        (row for row in manifest_document["rows"] if row["partition"] == "final"),
        key=lambda row: (row["project_id"], row["research_id"]),
    )
    sources = bind_verified_partition_sources(
        manifest_path,
        layout,
        "final",
        expected_count=18,
        generation=arguments.generation,
    )
    routing = json.loads(
        layout.resolve(
            "manifests", f"generation-{arguments.generation}-standard-routing.private.json"
        ).read_text(encoding="utf-8")
    )["routes"]
    calibration_document = json.loads(
        layout.resolve(
            "results", "development", f"generation-{arguments.generation}", "calibration-record.json"
        ).read_text(encoding="utf-8")
    )
    contract = acceptance_contract_from_calibration(
        calibration_record_from_dict(calibration_document["calibration"])
    )
    salt = layout.resolve("secrets", f"generation-{arguments.generation}-cohort-salt.bin").read_bytes()
    readers: list[_ThreadedSlideReader] = []
    slide_inputs: list[FinalSlideInput] = []
    manifest_rows: list[SlideRecord] = []
    try:
        import openslide

        for source, row in zip(sources, final_rows, strict=True):
            slide = openslide.OpenSlide(str(source.path))
            try:
                width, height = slide.dimensions
                mpp = resolve_mpp_in_band(slide.properties, minimum=0.20, maximum=0.30)
            finally:
                slide.close()
            reader = _ThreadedSlideReader(source.path)
            readers.append(reader)
            slide_inputs.append(
                FinalSlideInput(
                    source.record.research_id,
                    width,
                    height,
                    512,
                    reader,
                    mpp,
                    source_candidate_builder=lambda address, path=source.path: (
                        build_source_segment_candidate_from_svs(path, address)
                    ),
                    standard_ladder=ladder_from_profile_ids(
                        tuple(str(value) for value in routing[source.record.project_id])
                    ),
                    close_reader=reader.close,
                )
            )
            manifest_rows.append(
                SlideRecord(
                    source.record.research_id,
                    source.record.project_id,
                    hmac.new(salt, source.record.case_id.encode(), hashlib.sha256).hexdigest(),
                    _sha256_file(source.path),
                    source.record.file_size,
                    "final",
                    None,
                )
            )
        partition_manifest = PartitionManifest(
            "MC-V1-manifest-1",
            int(manifest_document["seed"]),
            tuple(manifest_rows),
            context.partition_manifest_digest,
        )
        output_root = layout.resolve(
            "results", "final", f"generation-{arguments.generation}", "containers"
        )
        with PrivateRunLock(layout, f"final-generation-{arguments.generation}"):
            result = run_final_holdout(
                FinalHoldoutConfig(
                    output_root,
                    tuple(slide_inputs),
                    context,
                    methods=("standard", "denser"),
                    cpu_workers=arguments.cpu_workers,
                    acceptance_contract=contract,
                    checkpoint_interval_tiles=96,
                    retain_address_debug_evidence=False,
                ),
                partition_manifest,
                freeze,
            )
        performance = summarize_final_performance(result.containers)
        summary = {
            "version": "DENSER-private-final-execution-1",
            "generation": arguments.generation,
            "freeze_digest": freeze.freeze_digest,
            "source_data_processed": True,
            "full_level0_grid": True,
            "slide_count": len(slide_inputs),
            "container_count": len(result.containers),
            "ledgers_match_files": result.ledgers_match_files,
            "random_tiles_independently_decodable": result.random_tiles_independently_decodable,
            "unresolved_acceptance_violations": result.unresolved_acceptance_violations,
            "performance": asdict(performance),
            "containers": [
                {
                    "method": container.method,
                    "path": str(container.path),
                    "complete_bytes": container.complete_bytes,
                    "tile_count": container.tile_count,
                    "encoding_seconds": container.encoding_seconds,
                    "cold_decode_seconds": list(container.cold_decode_seconds),
                    "warm_decode_seconds": list(container.warm_decode_seconds),
                }
                for container in result.containers
            ],
        }
        summary_path = layout.resolve(
            "results", "final", f"generation-{arguments.generation}", "execution-summary.private.json"
        )
        summary_path.write_bytes(canonical_json_bytes(summary) + b"\n")
        print(
            json.dumps(
                {
                    "slides": len(slide_inputs),
                    "containers": len(result.containers),
                    "unresolved_violations": result.unresolved_acceptance_violations,
                    "ledgers_match": result.ledgers_match_files,
                    "random_access": result.random_tiles_independently_decodable,
                },
                sort_keys=True,
            )
        )
    finally:
        for reader in readers:
            reader.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
