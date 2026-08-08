from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from denser.certificates.encode import build_certificate
from denser.certificates.verify import verify_certificate
from denser.codecs.lossless import SharedLosslessCodec
from denser.container.mcv1 import McV1Reader, McV1Writer
from denser.core.errors import PartitionViolation
from denser.core.models import TileAddress
from denser.data.manifest import PartitionManifest
from denser.evidence.types import AcceptanceContract
from denser.experiments.freeze import FreezeContext, FreezeRecord, verify_freeze_record
from denser.experiments.synthetic import _candidate_for, _decode_packet, _decoded, _packet
from denser.method.candidates import CandidateProfile


@dataclass(frozen=True, slots=True)
class FinalSlideInput:
    research_id: str
    width: int
    height: int
    tile_size: int
    read_tile: Callable[[TileAddress], np.ndarray]


@dataclass(frozen=True, slots=True)
class FinalHoldoutConfig:
    output_root: Path
    slides: tuple[FinalSlideInput, ...]
    freeze_context: FreezeContext
    sampled_tile_extrapolation_for_primary_endpoint_allowed: bool = False
    methods: tuple[str, ...] = ("standard", "uniform", "denser")
    candidate_steps: tuple[float, ...] = (1.0, 2.0, 4.0)

    def __post_init__(self) -> None:
        if self.sampled_tile_extrapolation_for_primary_endpoint_allowed:
            raise ValueError("sampled tile extrapolation is prohibited for the primary endpoint")
        if self.methods != ("standard", "uniform", "denser"):
            raise ValueError("final method set is frozen")


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
    contract = AcceptanceContract(visual_relative_tolerance=1.0)
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
            path = root / f"final-{slide_number:03d}.{method}.mcv1"
            writer = McV1Writer(path)
            try:
                for address in addresses:
                    tile = np.asarray(slide.read_tile(address))
                    expected_shape = (address.height, address.width, 3)
                    if tile.dtype != np.uint8 or tile.shape != expected_shape:
                        raise ValueError("final tile loader returned invalid pixels")
                    candidate = _candidate_for(method, tile, profile)
                    decoded = _decoded(candidate, expected_shape)
                    certificate = build_certificate(tile, candidate, contract)
                    if not verify_certificate(decoded, certificate, contract).passed:
                        candidate = SharedLosslessCodec().encode(tile)
                        decoded = _decoded(candidate, expected_shape)
                        certificate = build_certificate(tile, candidate, contract)
                        if not verify_certificate(decoded, certificate, contract).passed:
                            unresolved += 1
                    packet, breakdown = _packet(method, tile, candidate, contract, b"")
                    writer.add_tile(address, packet, breakdown)
                    key = (method, address)
                    counts[key] = counts.get(key, 0) + 1
                    encoded_addresses.add(address)
                writer.finalize()
            except Exception:
                writer.abort()
                raise
            reader = McV1Reader(path)
            ledger = reader.byte_ledger()
            ledgers_match &= ledger.complete_bytes == path.stat().st_size
            for address in (addresses[0], addresses[-1]):
                tile = _decode_packet(reader.read_tile(address), (address.height, address.width, 3))
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
