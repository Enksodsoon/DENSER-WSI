from __future__ import annotations

import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry, build_default_registry
from denser.codecs.quadtree import build_jpeg_quadtree_candidates
from denser.codecs.standard import StandardLadder, build_standard_candidates
from denser.container.mcv2 import McV2Reader, McV2Writer
from denser.core.canonical import canonical_json_bytes
from denser.core.errors import PartitionViolation
from denser.core.models import TileAddress
from denser.data.manifest import PartitionManifest
from denser.evidence.localized import LocalizedAcceptanceVerifier
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.experiments.candidate_selection import (
    AcceptedTileCandidate,
    choose_smallest_accepted_result,
    decode_and_verify_tile_packet,
    select_smallest_accepted_candidate,
)
from denser.experiments.freeze import FreezeContext, FreezeRecord, verify_freeze_record
from denser.method.candidates import CandidateProfile, build_denser_candidates, build_uniform_candidates


@dataclass(frozen=True, slots=True)
class FinalSlideInput:
    research_id: str
    width: int
    height: int
    tile_size: int
    read_tile: Callable[[TileAddress], np.ndarray]
    mpp: float = 0.25
    source_candidate_builder: Callable[[TileAddress], EncodedCandidate] | None = None
    standard_ladder: StandardLadder | None = None


@dataclass(frozen=True, slots=True)
class FinalHoldoutConfig:
    output_root: Path
    slides: tuple[FinalSlideInput, ...]
    freeze_context: FreezeContext
    sampled_tile_extrapolation_for_primary_endpoint_allowed: bool = False
    methods: tuple[str, ...] = ("standard", "uniform", "denser")
    candidate_steps: tuple[float, ...] = (1.0, 2.0, 4.0)
    cpu_workers: int = 6
    standard_ladder: StandardLadder = StandardLadder()
    standard_builder: Callable[[np.ndarray, StandardLadder], list[EncodedCandidate]] = build_standard_candidates
    quadtree_builder: Callable[[np.ndarray, np.ndarray], list[EncodedCandidate]] = build_jpeg_quadtree_candidates
    codec_registry: CodecRegistry | None = None
    acceptance_contract: AcceptanceContract = AcceptanceContract()
    checkpoint_interval_tiles: int = 96

    def __post_init__(self) -> None:
        if self.sampled_tile_extrapolation_for_primary_endpoint_allowed:
            raise ValueError("sampled tile extrapolation is prohibited for the primary endpoint")
        if self.methods not in {
            ("standard", "uniform", "denser"),
            ("standard", "denser"),
        }:
            raise ValueError("final method set is frozen")
        if self.methods == ("standard", "denser") and any(
            slide.source_candidate_builder is None for slide in self.slides
        ):
            raise ValueError("source-extension final method requires a bound candidate builder")
        if not 1 <= self.cpu_workers <= 6:
            raise ValueError("final CPU workers must be between one and six")
        if self.checkpoint_interval_tiles <= 0:
            raise ValueError("final checkpoint interval must be positive")


@dataclass(frozen=True, slots=True)
class FinalContainerResult:
    method: str
    path: Path
    complete_bytes: int
    tile_count: int


@dataclass(frozen=True, slots=True)
class FinalHoldoutResult:
    encoded_addresses: set[TileAddress]
    address_method_counts: dict[tuple[str, str, TileAddress], int]
    containers: tuple[FinalContainerResult, ...]
    ledgers_match_files: bool
    random_tiles_independently_decodable: bool
    unresolved_acceptance_violations: int


def iter_level0_grid(width: int, height: int, tile_size: int) -> Iterator[TileAddress]:
    if min(width, height, tile_size) <= 0:
        raise ValueError("grid dimensions must be positive")
    for x in range(0, width, tile_size):
        for y in range(0, height, tile_size):
            yield TileAddress(0, x, y, min(tile_size, width - x), min(tile_size, height - y))


def _atomic_json(path: Path, document: dict[str, object]) -> None:
    payload = canonical_json_bytes(document) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _progress_document(
    freeze: FreezeRecord, research_id: str, completed_tiles: int
) -> dict[str, object]:
    unsigned = {
        "version": "DENSER-final-slide-progress-1",
        "freeze_digest": freeze.freeze_digest,
        "research_id": research_id,
        "completed_tiles": completed_tiles,
    }
    return {**unsigned, "sha256": hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()}


def _load_progress(
    path: Path, freeze: FreezeRecord, research_id: str
) -> int:
    if not path.exists():
        return 0
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        digest = document.pop("sha256")
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise RuntimeError("final slide progress checkpoint is invalid") from error
    if (
        digest != hashlib.sha256(canonical_json_bytes(document)).hexdigest()
        or document.get("version") != "DENSER-final-slide-progress-1"
        or document.get("freeze_digest") != freeze.freeze_digest
        or document.get("research_id") != research_id
        or not isinstance(document.get("completed_tiles"), int)
    ):
        raise RuntimeError("final slide progress checkpoint identity is invalid")
    return int(document["completed_tiles"])


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def run_final_holdout(
    config: FinalHoldoutConfig,
    manifest: PartitionManifest,
    freeze: FreezeRecord,
) -> FinalHoldoutResult:
    if any(row.partition != "final" for row in manifest.rows):
        raise PartitionViolation("final holdout accepts final rows only")
    manifest_ids = {row.research_id for row in manifest.rows}
    slide_ids = {slide.research_id for slide in config.slides}
    if manifest_ids != slide_ids:
        raise PartitionViolation("bound final slides do not exactly match the frozen manifest")
    if len(config.slides) != freeze.expected_final_slide_count:
        raise PartitionViolation("bound final slide count differs from the freeze")
    profile = CandidateProfile(config.candidate_steps)
    contract = config.acceptance_contract
    registry = config.codec_registry or build_default_registry()
    counts: dict[tuple[str, str, TileAddress], int] = {}
    encoded_addresses: set[TileAddress] = set()
    containers: list[FinalContainerResult] = []
    ledgers_match = True
    independent = True
    unresolved = 0
    root = Path(config.output_root)
    root.mkdir(parents=True, exist_ok=True)
    for slide_number, slide in enumerate(config.slides):
        verify_freeze_record(freeze, config.freeze_context)
        addresses = tuple(iter_level0_grid(slide.width, slide.height, slide.tile_size))
        paths = {
            method: root / f"final-{slide_number:03d}.{method}.mcv2"
            for method in config.methods
        }
        progress_path = root / f".final-{slide_number:03d}.progress.json"
        completion_path = root / f"final-{slide_number:03d}.complete.json"
        existing = {method for method, path in paths.items() if path.exists()}
        if existing and existing != set(config.methods):
            raise RuntimeError("final slide has a partially finalized method set")
        if completion_path.exists() != bool(existing):
            raise RuntimeError("final slide completion marker and containers disagree")
        writers: dict[str, McV2Writer] = {}

        def encode_address(address: TileAddress):  # type: ignore[no-untyped-def]
            tile = np.asarray(slide.read_tile(address))
            expected_shape = (address.height, address.width, 3)
            if tile.dtype != np.uint8 or tile.shape != expected_shape:
                raise ValueError("final tile loader returned invalid pixels")
            grid = PhysicalGrid(slide.mpp, slide.mpp)
            cell_size_px = max(1, round(8.0 / slide.mpp))
            prepared_verifier = LocalizedAcceptanceVerifier(
                contract, cell_size_px, grid
            ).prepare(tile)
            encoded_methods = []
            sensitivity: np.ndarray | None = None
            standard_selected: AcceptedTileCandidate | None = None
            for method in config.methods:
                if method == "standard":
                    candidates = config.standard_builder(
                        tile, slide.standard_ladder or config.standard_ladder
                    )
                elif method == "uniform":
                    candidates = build_uniform_candidates(tile, profile)
                elif slide.source_candidate_builder is not None:
                    candidates = [slide.source_candidate_builder(address)]
                else:
                    if sensitivity is None:
                        values = tile.astype(np.float64)
                        sensitivity = np.empty_like(values)
                        for channel in range(3):
                            if min(values.shape[:2]) < 2:
                                sensitivity[:, :, channel] = 1.0
                            else:
                                gy, gx = np.gradient(values[:, :, channel])
                                sensitivity[:, :, channel] = np.hypot(gx, gy) + 1.0
                    candidates = build_denser_candidates(tile, sensitivity, profile)
                    candidates.extend(config.quadtree_builder(tile, sensitivity))
                selected = select_smallest_accepted_candidate(
                    tile,
                    candidates,
                    registry,
                    contract,
                    grid,
                    cell_size_px=cell_size_px,
                    prepared_verifier=prepared_verifier,
                )
                if method == "standard":
                    standard_selected = selected
                elif method == "denser" and slide.source_candidate_builder is not None:
                    if standard_selected is None:
                        raise RuntimeError("source extension requires the standard result first")
                    selected = choose_smallest_accepted_result(
                        standard_selected, selected
                    )
                encoded_methods.append(
                    (method, selected.packet, selected.breakdown, 0)
                )
            return address, encoded_methods

        if not existing:
            writers = {
                method: McV2Writer(
                    path,
                    resume_token=f"{freeze.freeze_digest}:{slide.research_id}:{method}",
                )
                for method, path in paths.items()
            }
            shared_count = _load_progress(progress_path, freeze, slide.research_id)
            if not 0 <= shared_count <= len(addresses):
                raise RuntimeError("final slide progress count is outside the tile grid")
            for writer in writers.values():
                checkpointed = writer.checkpointed_addresses
                if len(checkpointed) < shared_count or checkpointed[:shared_count] != addresses[:shared_count]:
                    raise RuntimeError("final slide writer disagrees with shared progress")
                writer.rollback_to_checkpoint(shared_count)
            try:
                tile_workers = min(3, config.cpu_workers)
                last_checkpoint = shared_count
                with ThreadPoolExecutor(max_workers=tile_workers) as pool:
                    for start in range(shared_count, len(addresses), tile_workers):
                        encoded = pool.map(
                            encode_address, addresses[start : start + tile_workers]
                        )
                        for address, encoded_methods in encoded:
                            for method, packet, breakdown, violation in encoded_methods:
                                writers[method].add_tile(address, packet, breakdown)
                                unresolved += violation
                        completed = min(start + tile_workers, len(addresses))
                        if (
                            completed == len(addresses)
                            or completed - last_checkpoint >= config.checkpoint_interval_tiles
                        ):
                            for writer in writers.values():
                                writer.checkpoint()
                            _atomic_json(
                                progress_path,
                                _progress_document(
                                    freeze, slide.research_id, completed
                                ),
                            )
                            last_checkpoint = completed
                for writer in writers.values():
                    writer.finalize()
            except Exception:
                for writer in writers.values():
                    writer.suspend()
                raise
            marker_unsigned: dict[str, object] = {
                "version": "DENSER-final-slide-completion-1",
                "freeze_digest": freeze.freeze_digest,
                "research_id": slide.research_id,
                "tile_count": len(addresses),
                "containers": {
                    method: {
                        "sha256": _file_sha256(path),
                        "complete_bytes": path.stat().st_size,
                    }
                    for method, path in paths.items()
                },
            }
            _atomic_json(
                completion_path,
                {
                    **marker_unsigned,
                    "sha256": hashlib.sha256(
                        canonical_json_bytes(marker_unsigned)
                    ).hexdigest(),
                },
            )
            progress_path.unlink(missing_ok=True)
        try:
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion_digest = completion.pop("sha256")
        except (OSError, KeyError, json.JSONDecodeError) as error:
            raise RuntimeError("final slide completion marker is invalid") from error
        if (
            completion_digest
            != hashlib.sha256(canonical_json_bytes(completion)).hexdigest()
            or completion.get("version") != "DENSER-final-slide-completion-1"
            or completion.get("freeze_digest") != freeze.freeze_digest
            or completion.get("research_id") != slide.research_id
            or completion.get("tile_count") != len(addresses)
            or set(completion.get("containers", {})) != set(config.methods)
        ):
            raise RuntimeError("final slide completion marker identity is invalid")
        for method, path in paths.items():
            marker_container = completion["containers"][method]
            if (
                marker_container.get("sha256") != _file_sha256(path)
                or marker_container.get("complete_bytes") != path.stat().st_size
            ):
                raise RuntimeError("final slide container differs from completion marker")
            reader = McV2Reader(path)
            if reader.addresses != addresses:
                raise RuntimeError("final slide container does not cover the exact level-0 grid")
            ledger = reader.byte_ledger()
            ledgers_match &= ledger.complete_bytes == path.stat().st_size
            for address in (addresses[0], addresses[-1]):
                tile = decode_and_verify_tile_packet(
                    reader.read_tile(address),
                    (address.height, address.width, 3),
                    registry,
                    contract,
                )
                independent &= tile.shape == (address.height, address.width, 3)
            containers.append(
                FinalContainerResult(method, path, ledger.complete_bytes, len(addresses))
            )
            for address in addresses:
                counts[(slide.research_id, method, address)] = 1
        encoded_addresses.update(addresses)
    return FinalHoldoutResult(
        encoded_addresses,
        counts,
        tuple(containers),
        ledgers_match,
        independent,
        unresolved,
    )
