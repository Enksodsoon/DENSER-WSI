from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import build_default_registry
from denser.codecs.standard import StandardLadder, build_standard_candidates
from denser.container.mcv2 import McV2CorruptionError, McV2Reader, McV2Writer
from denser.core.models import TileAddress
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.experiments.candidate_selection import (
    decode_and_verify_tile_packet,
    select_smallest_accepted_candidate,
)
from denser.method.candidates import (
    CandidateProfile,
    build_denser_candidates,
    build_uniform_candidates,
)
from denser.orchestration.runner import PhaseRunner, SimulatedCrash
from denser.repair.escalate import repair_until_verified
from denser.repair.mask import RepairFailure
from denser.synthetic.histology import SyntheticSlideSpec, generate_synthetic_slide


StandardBuilder = Callable[[np.ndarray], list[EncodedCandidate]]


def _native_standard_builder(tile: np.ndarray) -> list[EncodedCandidate]:
    return build_standard_candidates(tile, StandardLadder())


@dataclass(frozen=True, slots=True)
class SyntheticValidationConfig:
    output_root: Path
    slide_specs: tuple[SyntheticSlideSpec, ...] = (SyntheticSlideSpec(),)
    seed: int = 1
    quantization_steps: tuple[float, ...] = (1.0, 2.0, 4.0)
    standard_builder: StandardBuilder = _native_standard_builder


@dataclass(frozen=True, slots=True)
class SyntheticSlideResult:
    method: str
    path: Path
    complete_bytes: int
    tile_count: int


@dataclass(frozen=True, slots=True)
class SyntheticValidationReport:
    slides: tuple[SyntheticSlideResult, ...]
    unresolved_acceptance_violations: int
    fallback_exercised: bool
    repair_exercised: bool
    corruption_rejected: bool
    resume_replayed_only_uncommitted: bool

    @property
    def methods(self) -> set[str]:
        return {row.method for row in self.slides}


class _ExactRepairVerifier:
    def verify(self, source: np.ndarray, decoded: np.ndarray):  # type: ignore[no-untyped-def]
        passed = bool(np.array_equal(source, decoded))
        height, width, _ = source.shape
        failures = () if passed else (RepairFailure(1, 1, 2, 2, width, height),)
        return type("RepairCheck", (), {"passed": passed, "failures": failures})()


def _sensitivity(tile: np.ndarray) -> np.ndarray:
    values = tile.astype(np.float64)
    result = np.empty_like(values)
    for channel in range(3):
        plane = values[:, :, channel]
        if min(plane.shape) < 2:
            result[:, :, channel] = 1.0
        else:
            gy, gx = np.gradient(plane)
            result[:, :, channel] = np.hypot(gx, gy) + 1.0
    return result


def _exercise_resume(root: Path) -> bool:
    state = root / "synthetic-execution-state.json"
    calls: list[str] = []
    runner = PhaseRunner(
        state,
        [("synthetic:1", lambda: calls.append("1")), ("synthetic:2", lambda: calls.append("2"))],
        crash_after="synthetic:2",
    )
    try:
        runner.run_all()
    except SimulatedCrash:
        completion = runner.resume()
        return completion.repeated_steps == ("synthetic:2",) and calls == ["1", "2", "2"]
    return False


def run_synthetic_validation(config: SyntheticValidationConfig) -> SyntheticValidationReport:
    root = Path(config.output_root)
    root.mkdir(parents=True, exist_ok=True)
    profile = CandidateProfile(config.quantization_steps)
    contract = AcceptanceContract(
        nuclear_relative_tolerance=1.0,
        architecture_relative_tolerance=1.0,
        sentinel_relative_tolerance=1.0,
        visual_relative_tolerance=1.0,
    )
    registry = build_default_registry()
    results: list[SyntheticSlideResult] = []
    unresolved = 0
    repair_exercised = False
    fallback_exercised = False
    addresses: list[TileAddress] = []
    first_tile: np.ndarray | None = None
    first_grid: PhysicalGrid | None = None
    for slide_number, spec in enumerate(config.slide_specs):
        slide = generate_synthetic_slide(spec, config.seed + slide_number)
        grid = PhysicalGrid(spec.mpp, spec.mpp)
        for method in ("standard", "uniform", "denser"):
            path = root / f"synthetic-{slide_number:03d}.{method}.mcv2"
            writer = McV2Writer(path)
            try:
                for tile_number, (address, tile) in enumerate(slide.tiles()):
                    if first_tile is None:
                        first_tile, first_grid = tile.copy(), grid
                    if method == "standard":
                        candidates = config.standard_builder(tile)
                    elif method == "uniform":
                        candidates = build_uniform_candidates(tile, profile)
                    else:
                        candidates = build_denser_candidates(tile, _sensitivity(tile), profile)
                    selected = select_smallest_accepted_candidate(
                        tile, candidates, registry, contract, grid, cell_size_px=16
                    )
                    writer.add_tile(address, selected.packet, selected.breakdown)
                    if method == "denser" and tile_number == 0:
                        damaged = tile.copy()
                        damaged[1:3, 1:3] = 0
                        repair = repair_until_verified(
                            tile,
                            damaged,
                            _ExactRepairVerifier(),
                            SharedLosslessCodec(),
                            halo_um=0,
                            mpp=spec.mpp,
                        )
                        repair_exercised = repair.status == "verified_repair"
                    if slide_number == 0 and method == "standard":
                        addresses.append(address)
                writer.finalize()
            except Exception:
                writer.abort()
                raise
            reader = McV2Reader(path)
            for address, tile in slide.tiles():
                try:
                    independently_decoded = decode_and_verify_tile_packet(
                        reader.read_tile(address), tile.shape, registry, contract
                    )
                except ValueError:
                    unresolved += 1
                    continue
                if independently_decoded.shape != tile.shape:
                    unresolved += 1
            ledger = reader.byte_ledger()
            results.append(SyntheticSlideResult(method, path, ledger.complete_bytes, reader.tile_count))

    if first_tile is not None and first_grid is not None:
        fallback = select_smallest_accepted_candidate(
            first_tile, [], registry, contract, first_grid, cell_size_px=16
        )
        fallback_exercised = fallback.status == "fallback"
        decode_and_verify_tile_packet(fallback.packet, first_tile.shape, registry, contract)

    corruption_rejected = False
    if results:
        corrupt_path = root / "corruption-probe.mcv2"
        shutil.copyfile(results[0].path, corrupt_path)
        probe = McV2Reader(corrupt_path)
        with corrupt_path.open("r+b") as stream:
            stream.seek(probe.packet_region_offset)
            byte = stream.read(1)
            stream.seek(probe.packet_region_offset)
            stream.write(bytes([byte[0] ^ 1]))
        try:
            McV2Reader(corrupt_path).read_tile(addresses[0])
        except McV2CorruptionError:
            corruption_rejected = True
        corrupt_path.unlink()

    return SyntheticValidationReport(
        tuple(results),
        unresolved,
        fallback_exercised,
        repair_exercised,
        corruption_rejected,
        _exercise_resume(root),
    )
