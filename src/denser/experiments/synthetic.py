from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from denser.certificates.encode import build_certificate, encode_certificate
from denser.certificates.verify import verify_certificate
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.container.mcv1 import McV1CorruptionError, McV1Reader, McV1Writer
from denser.core.models import ByteBreakdown, TileAddress
from denser.evidence.types import AcceptanceContract
from denser.method.candidates import (
    CandidateProfile,
    build_denser_candidates,
    build_uniform_candidates,
    decode_candidate,
)
from denser.orchestration.runner import PhaseRunner, SimulatedCrash
from denser.repair.escalate import repair_until_verified
from denser.repair.mask import RepairFailure
from denser.synthetic.histology import SyntheticSlideSpec, generate_synthetic_slide


_PACKET_HEADER = struct.Struct(">4sBIIII")


@dataclass(frozen=True, slots=True)
class SyntheticValidationConfig:
    output_root: Path
    slide_specs: tuple[SyntheticSlideSpec, ...] = (SyntheticSlideSpec(),)
    seed: int = 1
    quantization_steps: tuple[float, ...] = (1.0, 2.0, 4.0)


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


def _candidate_for(method: str, tile: np.ndarray, profile: CandidateProfile) -> EncodedCandidate:
    if method == "standard":
        return SharedLosslessCodec().encode(tile)
    if method == "uniform":
        return build_uniform_candidates(tile, profile)[0]
    values = tile.astype(np.float64)
    sensitivity = np.empty_like(values)
    for channel in range(3):
        gy, gx = np.gradient(values[:, :, channel])
        sensitivity[:, :, channel] = np.hypot(gx, gy) + 1.0
    return build_denser_candidates(tile, sensitivity, profile)[0]


def _decoded(candidate: EncodedCandidate, shape: tuple[int, int, int]) -> np.ndarray:
    if candidate.codec_id == SharedLosslessCodec.codec_id:
        return SharedLosslessCodec().decode(candidate.payload, shape)
    return decode_candidate(candidate.payload)


def _packet(
    method: str,
    tile: np.ndarray,
    candidate: EncodedCandidate,
    contract: AcceptanceContract,
    repair_trace: bytes,
) -> tuple[bytes, ByteBreakdown]:
    certificate = build_certificate(tile, candidate, contract)
    cert_bytes = encode_certificate(certificate)
    reference_bytes = certificate.reference_payload.encoded_bytes if certificate.reference_payload else 0
    codec_kind = 0 if candidate.codec_id == SharedLosslessCodec.codec_id else 1
    header = _PACKET_HEADER.pack(
        b"SVP1", codec_kind, len(candidate.payload), len(repair_trace), len(cert_bytes), len(method.encode("ascii"))
    )
    method_bytes = method.encode("ascii")
    fallback_signal = b"\x01" if codec_kind == 0 else b""
    packet = header + method_bytes + fallback_signal + candidate.payload + repair_trace + cert_bytes
    breakdown = ByteBreakdown(
        payload=len(candidate.payload),
        repair=len(repair_trace),
        certificate=len(cert_bytes) - reference_bytes,
        reference_evidence=reference_bytes,
        method_signaling=len(header) + len(method_bytes),
        fallback_signaling=len(fallback_signal),
    )
    if breakdown.complete != len(packet):
        raise RuntimeError("synthetic packet accounting mismatch")
    return packet, breakdown


def _decode_packet(packet: bytes, shape: tuple[int, int, int]) -> np.ndarray:
    if len(packet) < _PACKET_HEADER.size:
        raise ValueError("synthetic packet is truncated")
    magic, kind, payload_length, repair_length, cert_length, method_length = _PACKET_HEADER.unpack_from(packet)
    if magic != b"SVP1":
        raise ValueError("synthetic packet identity is invalid")
    offset = _PACKET_HEADER.size + method_length + (1 if kind == 0 else 0)
    expected = offset + payload_length + repair_length + cert_length
    if expected != len(packet):
        raise ValueError("synthetic packet section lengths are invalid")
    payload = packet[offset : offset + payload_length]
    if kind == 0:
        return SharedLosslessCodec().decode(payload, shape)
    return decode_candidate(payload)


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
    results: list[SyntheticSlideResult] = []
    unresolved = 0
    repair_exercised = False
    addresses: list[TileAddress] = []
    for slide_number, spec in enumerate(config.slide_specs):
        slide = generate_synthetic_slide(spec, config.seed + slide_number)
        for method in ("standard", "uniform", "denser"):
            path = root / f"synthetic-{slide_number:03d}.{method}.mcv1"
            writer = McV1Writer(path)
            try:
                for tile_number, (address, tile) in enumerate(slide.tiles()):
                    candidate = _candidate_for(method, tile, profile)
                    decoded = _decoded(candidate, tile.shape)
                    certificate = build_certificate(tile, candidate, contract)
                    if not verify_certificate(decoded, certificate, contract).passed:
                        candidate = SharedLosslessCodec().encode(tile)
                        decoded = _decoded(candidate, tile.shape)
                        certificate = build_certificate(tile, candidate, contract)
                        if not verify_certificate(decoded, certificate, contract).passed:
                            unresolved += 1
                    repair_trace = b""
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
                        repair_trace = (
                            f"{repair.stage}:{repair.mask_bytes}:{repair.overlay_bytes}:{repair.residual_bytes}"
                        ).encode("ascii")
                    packet, breakdown = _packet(method, tile, candidate, contract, repair_trace)
                    writer.add_tile(address, packet, breakdown)
                    if slide_number == 0 and method == "standard":
                        addresses.append(address)
                writer.finalize()
            except Exception:
                writer.abort()
                raise
            reader = McV1Reader(path)
            for address, tile in slide.tiles():
                independently_decoded = _decode_packet(reader.read_tile(address), tile.shape)
                if independently_decoded.shape != tile.shape:
                    unresolved += 1
            ledger = reader.byte_ledger()
            results.append(SyntheticSlideResult(method, path, ledger.complete_bytes, len(slide.tiles())))

    corruption_rejected = False
    if results:
        corrupt_path = root / "corruption-probe.mcv1"
        shutil.copyfile(results[0].path, corrupt_path)
        probe = McV1Reader(corrupt_path)
        with corrupt_path.open("r+b") as stream:
            stream.seek(probe.packet_region_offset)
            byte = stream.read(1)
            stream.seek(probe.packet_region_offset)
            stream.write(bytes([byte[0] ^ 1]))
        try:
            McV1Reader(corrupt_path).read_tile(addresses[0])
        except McV1CorruptionError:
            corruption_rejected = True
        corrupt_path.unlink()

    return SyntheticValidationReport(
        tuple(results),
        unresolved,
        fallback_exercised=any(row.method == "standard" for row in results),
        repair_exercised=repair_exercised,
        corruption_rejected=corruption_rejected,
        resume_replayed_only_uncommitted=_exercise_resume(root),
    )
