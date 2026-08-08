from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry, build_default_registry
from denser.codecs.quadtree import build_jpegxl_quadtree_candidates
from denser.codecs.standard import StandardLadder, build_standard_candidates
from denser.container.mcv2 import McV2Reader, McV2Writer
from denser.core.errors import PartitionViolation
from denser.core.models import TileAddress
from denser.data.manifest import PartitionManifest
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.experiments.candidate_selection import (
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
    quadtree_builder: Callable[[np.ndarray, np.ndarray], list[EncodedCandidate]] = build_jpegxl_quadtree_candidates
    codec_registry: CodecRegistry | None = None
    acceptance_contract: AcceptanceContract = AcceptanceContract()

    def __post_init__(self) -> None:
        if self.sampled_tile_extrapolation_for_primary_endpoint_allowed:
            raise ValueError("sampled tile extrapolation is prohibited for the primary endpoint")
        if self.methods != ("standard", "uniform", "denser"):
            raise ValueError("final method set is frozen")
        if not 1 <= self.cpu_workers <= 6:
            raise ValueError("final CPU workers must be between one and six")


@dataclass(frozen=True, slots=True)
class FinalContainerResult:
    method: str
    path: Path
    complete_bytes: int
    tile_count: int


@dataclass(frozen=True, slots=True)
class FinalHoldoutResult:
    encoded_addresses: set[TileAddress]
    address_method_counts: dict[tuple[str, TileAddress], int]
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
    counts: dict[tuple[str, TileAddress], int] = {}
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
        for method in config.methods:
            path = root / f"final-{slide_number:03d}.{method}.mcv2"
            writer = McV2Writer(path)

            def encode_address(address: TileAddress):  # type: ignore[no-untyped-def]
                tile = np.asarray(slide.read_tile(address))
                expected_shape = (address.height, address.width, 3)
                if tile.dtype != np.uint8 or tile.shape != expected_shape:
                    raise ValueError("final tile loader returned invalid pixels")
                if method == "standard":
                    candidates = config.standard_builder(tile, config.standard_ladder)
                elif method == "uniform":
                    candidates = build_uniform_candidates(tile, profile)
                else:
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
                    PhysicalGrid(slide.mpp, slide.mpp),
                    cell_size_px=max(1, round(8.0 / slide.mpp)),
                )
                return address, selected.packet, selected.breakdown, 0

            try:
                tile_workers = max(1, min(3, config.cpu_workers // 2))
                with ThreadPoolExecutor(max_workers=tile_workers) as pool:
                    encoded = pool.map(encode_address, addresses)
                    for address, packet, breakdown, violation in encoded:
                        unresolved += violation
                        writer.add_tile(address, packet, breakdown)
                        key = (method, address)
                        counts[key] = counts.get(key, 0) + 1
                        encoded_addresses.add(address)
                writer.finalize()
            except Exception:
                writer.abort()
                raise
            reader = McV2Reader(path)
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
            containers.append(FinalContainerResult(method, path, ledger.complete_bytes, len(addresses)))
    return FinalHoldoutResult(
        encoded_addresses,
        counts,
        tuple(containers),
        ledgers_match,
        independent,
        unresolved,
    )
