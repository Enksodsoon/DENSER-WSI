from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
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
    decode_and_verify_tile_packet,
    prepare_candidate_selection,
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
    close_reader: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class FinalHoldoutConfig:
    output_root: Path
    slides: tuple[FinalSlideInput, ...]
    freeze_context: FreezeContext
    sampled_tile_extrapolation_for_primary_endpoint_allowed: bool = False
    methods: tuple[str, ...] = ("standard", "uniform", "denser")
    candidate_steps: tuple[float, ...] = (1.0, 2.0, 4.0)
    cpu_workers: int = 6
    candidate_workers: int = 1
    max_codec_subprocesses: int = 2
    standard_ladder: StandardLadder = StandardLadder()
    standard_builder: Callable[[np.ndarray, StandardLadder], list[EncodedCandidate]] = build_standard_candidates
    quadtree_builder: Callable[[np.ndarray, np.ndarray], list[EncodedCandidate]] = build_jpeg_quadtree_candidates
    codec_registry: CodecRegistry | None = None
    acceptance_contract: AcceptanceContract = AcceptanceContract()
    checkpoint_interval_tiles: int = 96
    random_access_probe_count: int = 16
    retain_address_debug_evidence: bool = True

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
        if not 1 <= self.candidate_workers <= 6:
            raise ValueError("final candidate workers must be between one and six")
        if not 1 <= self.max_codec_subprocesses <= 2:
            raise ValueError("final codec subprocesses must be one or two")
        if self.checkpoint_interval_tiles <= 0:
            raise ValueError("final checkpoint interval must be positive")
        if self.random_access_probe_count <= 0:
            raise ValueError("random-access probe count must be positive")


@dataclass(frozen=True, slots=True)
class FinalContainerResult:
    method: str
    path: Path
    complete_bytes: int
    tile_count: int
    encoding_seconds: float
    cold_decode_seconds: tuple[float, ...]
    warm_decode_seconds: tuple[float, ...]

    @property
    def random_probe_count(self) -> int:
        return len(self.cold_decode_seconds)


@dataclass(frozen=True, slots=True)
class FinalHoldoutResult:
    encoded_addresses: set[TileAddress]
    address_method_counts: dict[tuple[str, str, TileAddress], int]
    containers: tuple[FinalContainerResult, ...]
    ledgers_match_files: bool
    random_tiles_independently_decodable: bool
    unresolved_acceptance_violations: int


@dataclass(frozen=True, slots=True)
class FinalPerformanceSummary:
    standard_encoding_seconds: float
    denser_encoding_seconds: float
    encoding_time_ratio: float
    standard_cold_decode_p95_seconds: float
    denser_cold_decode_p95_seconds: float
    cold_decode_p95_ratio: float
    standard_warm_decode_p95_seconds: float
    denser_warm_decode_p95_seconds: float
    warm_decode_p95_ratio: float
    random_probe_observations: int


def summarize_final_performance(
    containers: tuple[FinalContainerResult, ...],
) -> FinalPerformanceSummary:
    by_method = {
        method: tuple(container for container in containers if container.method == method)
        for method in ("standard", "denser")
    }
    if not all(by_method.values()) or len(by_method["standard"]) != len(by_method["denser"]):
        raise ValueError("final performance requires paired standard and DENSER containers")
    standard_encoding = sum(value.encoding_seconds for value in by_method["standard"])
    denser_encoding = sum(value.encoding_seconds for value in by_method["denser"])
    if standard_encoding <= 0:
        raise ValueError("standard encoding time must be positive")

    def samples(method: str, field: str) -> tuple[float, ...]:
        return tuple(
            value
            for container in by_method[method]
            for value in getattr(container, field)
        )

    standard_cold = samples("standard", "cold_decode_seconds")
    denser_cold = samples("denser", "cold_decode_seconds")
    standard_warm = samples("standard", "warm_decode_seconds")
    denser_warm = samples("denser", "warm_decode_seconds")
    if not all((standard_cold, denser_cold, standard_warm, denser_warm)):
        raise ValueError("final performance requires random-access decode observations")
    if len(standard_cold) != len(denser_cold) or len(standard_warm) != len(denser_warm):
        raise ValueError("final performance decode observations are unpaired")
    p95 = lambda values: float(np.percentile(np.asarray(values), 95))
    standard_cold_p95 = p95(standard_cold)
    denser_cold_p95 = p95(denser_cold)
    standard_warm_p95 = p95(standard_warm)
    denser_warm_p95 = p95(denser_warm)
    if min(standard_cold_p95, standard_warm_p95) <= 0:
        raise ValueError("standard decode p95 must be positive")
    return FinalPerformanceSummary(
        standard_encoding,
        denser_encoding,
        denser_encoding / standard_encoding,
        standard_cold_p95,
        denser_cold_p95,
        denser_cold_p95 / standard_cold_p95,
        standard_warm_p95,
        denser_warm_p95,
        denser_warm_p95 / standard_warm_p95,
        len(standard_cold) + len(denser_cold),
    )


def iter_level0_grid(width: int, height: int, tile_size: int) -> Iterator[TileAddress]:
    if min(width, height, tile_size) <= 0:
        raise ValueError("grid dimensions must be positive")
    for x in range(0, width, tile_size):
        for y in range(0, height, tile_size):
            yield TileAddress(0, x, y, min(tile_size, width - x), min(tile_size, height - y))


def select_random_access_probes(
    addresses: tuple[TileAddress, ...],
    freeze_digest: str,
    research_id: str,
    count: int,
) -> tuple[TileAddress, ...]:
    """Choose freeze-bound pseudo-random addresses without reading outcomes."""
    if count <= 0:
        raise ValueError("random-access probe count must be positive")
    identity = f"{freeze_digest}:{research_id}:".encode("utf-8")

    def rank(address: TileAddress) -> tuple[bytes, TileAddress]:
        coordinate = (
            f"{address.level}:{address.x}:{address.y}:"
            f"{address.width}:{address.height}"
        ).encode("ascii")
        return hashlib.sha256(identity + coordinate).digest(), address

    ranked = sorted(addresses, key=rank)
    return tuple(ranked[: min(count, len(ranked))])


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
    freeze: FreezeRecord,
    research_id: str,
    completed_tiles: int,
    encoding_seconds_by_method: dict[str, float],
) -> dict[str, object]:
    unsigned = {
        "version": "DENSER-final-slide-progress-2",
        "freeze_digest": freeze.freeze_digest,
        "research_id": research_id,
        "completed_tiles": completed_tiles,
        "encoding_seconds_by_method": encoding_seconds_by_method,
    }
    return {**unsigned, "sha256": hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()}


def _load_progress(
    path: Path,
    freeze: FreezeRecord,
    research_id: str,
    methods: tuple[str, ...],
) -> tuple[int, dict[str, float]]:
    if not path.exists():
        return 0, {method: 0.0 for method in methods}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        digest = document.pop("sha256")
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise RuntimeError("final slide progress checkpoint is invalid") from error
    if (
        digest != hashlib.sha256(canonical_json_bytes(document)).hexdigest()
        or document.get("version") != "DENSER-final-slide-progress-2"
        or document.get("freeze_digest") != freeze.freeze_digest
        or document.get("research_id") != research_id
        or not isinstance(document.get("completed_tiles"), int)
    ):
        raise RuntimeError("final slide progress checkpoint identity is invalid")
    timings = document.get("encoding_seconds_by_method")
    if (
        not isinstance(timings, dict)
        or set(timings) != set(methods)
        or any(
            not isinstance(value, (int, float)) or value < 0
            for value in timings.values()
        )
    ):
        raise RuntimeError("final slide progress timings are invalid")
    return int(document["completed_tiles"]), {
        method: float(timings[method]) for method in methods
    }


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
        encoding_seconds_by_method = {method: 0.0 for method in config.methods}
        codec_slots = threading.Semaphore(config.max_codec_subprocesses)

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
            prepared_selection = prepare_candidate_selection(
                tile,
                contract,
                grid,
                cell_size_px=cell_size_px,
                prepared_verifier=prepared_verifier,
            )
            encoded_methods = []
            sensitivity: np.ndarray | None = None
            standard_selected: AcceptedTileCandidate | None = None
            standard_elapsed = 0.0
            for method in config.methods:
                started = time.perf_counter()
                if method == "standard":
                    with codec_slots:
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
                    prepared_selection=prepared_selection,
                    incumbent=(
                        standard_selected
                        if method == "denser" and slide.source_candidate_builder is not None
                        else None
                    ),
                    max_candidate_workers=config.candidate_workers,
                )
                if method == "standard":
                    standard_selected = selected
                    standard_elapsed = time.perf_counter() - started
                    elapsed = standard_elapsed
                elif method == "denser" and slide.source_candidate_builder is not None:
                    if standard_selected is None:
                        raise RuntimeError("source extension requires the standard result first")
                    elapsed = standard_elapsed + (time.perf_counter() - started)
                else:
                    elapsed = time.perf_counter() - started
                encoded_methods.append(
                    (method, selected.packet, selected.breakdown, 0, elapsed)
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
            shared_count, encoding_seconds_by_method = _load_progress(
                progress_path, freeze, slide.research_id, config.methods
            )
            if not 0 <= shared_count <= len(addresses):
                raise RuntimeError("final slide progress count is outside the tile grid")
            for writer in writers.values():
                checkpointed = writer.checkpointed_addresses
                if len(checkpointed) < shared_count or checkpointed[:shared_count] != addresses[:shared_count]:
                    raise RuntimeError("final slide writer disagrees with shared progress")
                writer.rollback_to_checkpoint(shared_count)
            try:
                tile_workers = config.cpu_workers
                last_checkpoint = shared_count
                with ThreadPoolExecutor(max_workers=tile_workers) as pool:
                    for start in range(shared_count, len(addresses), tile_workers):
                        encoded = pool.map(
                            encode_address, addresses[start : start + tile_workers]
                        )
                        for address, encoded_methods in encoded:
                            for method, packet, breakdown, violation, elapsed in encoded_methods:
                                writers[method].add_tile(address, packet, breakdown)
                                unresolved += violation
                                encoding_seconds_by_method[method] += elapsed
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
                                    freeze,
                                    slide.research_id,
                                    completed,
                                    encoding_seconds_by_method,
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
                "version": "DENSER-final-slide-completion-2",
                "freeze_digest": freeze.freeze_digest,
                "research_id": slide.research_id,
                "tile_count": len(addresses),
                "encoding_seconds_by_method": encoding_seconds_by_method,
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
            or completion.get("version") != "DENSER-final-slide-completion-2"
            or completion.get("freeze_digest") != freeze.freeze_digest
            or completion.get("research_id") != slide.research_id
            or completion.get("tile_count") != len(addresses)
            or set(completion.get("containers", {})) != set(config.methods)
        ):
            raise RuntimeError("final slide completion marker identity is invalid")
        marker_timings = completion.get("encoding_seconds_by_method")
        if (
            not isinstance(marker_timings, dict)
            or set(marker_timings) != set(config.methods)
            or any(
                not isinstance(value, (int, float)) or value <= 0
                for value in marker_timings.values()
            )
        ):
            raise RuntimeError("final slide completion timings are invalid")
        probes = select_random_access_probes(
            addresses,
            freeze.freeze_digest,
            slide.research_id,
            config.random_access_probe_count,
        )
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
            decode_passes: list[tuple[float, ...]] = []
            for _pass in range(2):
                decode_seconds: list[float] = []
                for address in probes:
                    started = time.perf_counter()
                    tile = decode_and_verify_tile_packet(
                        reader.read_tile(address),
                        (address.height, address.width, 3),
                        registry,
                        contract,
                    )
                    decode_seconds.append(time.perf_counter() - started)
                    independent &= tile.shape == (address.height, address.width, 3)
                decode_passes.append(tuple(decode_seconds))
            containers.append(
                FinalContainerResult(
                    method,
                    path,
                    ledger.complete_bytes,
                    len(addresses),
                    float(marker_timings[method]),
                    decode_passes[0],
                    decode_passes[1],
                )
            )
            if config.retain_address_debug_evidence:
                for address in addresses:
                    counts[(slide.research_id, method, address)] = 1
        if config.retain_address_debug_evidence:
            encoded_addresses.update(addresses)
        if slide.close_reader is not None:
            slide.close_reader()
    return FinalHoldoutResult(
        encoded_addresses,
        counts,
        tuple(containers),
        ledgers_match,
        independent,
        unresolved,
    )
