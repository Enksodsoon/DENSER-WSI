from __future__ import annotations

import hashlib
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from denser.adapter.pathlab_contract import PathLabAdapterContract
from denser.certificates.encode import decode_certificate
from denser.certificates.verify import verify_certificate
from denser.codecs.lossless import SharedLosslessCodec
from denser.container.mcv1 import McV1Reader
from denser.container.mcv2 import MAGIC as MCV2_MAGIC
from denser.container.mcv2 import McV2Reader
from denser.container.packet_v2 import McV2TilePacket
from denser.core.models import TileAddress
from denser.experiments.candidate_selection import decode_and_verify_tile_packet
from denser.codecs.registry import build_default_registry
from denser.method.candidates import decode_candidate
from denser.repair.packet_v2 import apply_repair_packet


_PACKET_HEADER = struct.Struct(">4sBIIIII")


@dataclass(frozen=True, slots=True)
class AdapterMetadata:
    format: str
    tile_count: int
    addresses: tuple[TileAddress, ...]
    complete_bytes: int
    open_latency_ms: float
    source_wsi_accessed: bool = False


@dataclass(frozen=True, slots=True)
class VerifiedTileResponse:
    rgb: np.ndarray
    address: TileAddress
    verification_passed: bool
    source_wsi_accessed: bool
    certificate_mode: str
    tile_latency_ms: float


def get_slide_metadata(path: Path) -> AdapterMetadata:
    start = time.perf_counter_ns()
    resolved = Path(path)
    with resolved.open("rb") as stream:
        is_v2 = stream.read(len(MCV2_MAGIC)) == MCV2_MAGIC
    reader = McV2Reader(resolved) if is_v2 else McV1Reader(resolved)
    latency = (time.perf_counter_ns() - start) / 1_000_000
    return AdapterMetadata(
        "MC-V2" if is_v2 else "MC-V1",
        reader.tile_count,
        reader.addresses,
        reader.byte_ledger().complete_bytes,
        latency,
    )


def get_tile(
    path: Path,
    address: TileAddress,
    contract: PathLabAdapterContract | None = None,
) -> VerifiedTileResponse:
    selected_contract = contract or PathLabAdapterContract()
    start = time.perf_counter_ns()
    resolved = Path(path)
    with resolved.open("rb") as stream:
        is_v2 = stream.read(len(MCV2_MAGIC)) == MCV2_MAGIC
    if is_v2:
        encoded = McV2Reader(resolved).read_tile(address)
        packet_v2 = McV2TilePacket.decode(encoded)
        certificate = decode_certificate(packet_v2.certificate)
        rgb = decode_and_verify_tile_packet(
            encoded,
            (address.height, address.width, 3),
            build_default_registry(),
            selected_contract.acceptance,
        )
        passed = not selected_contract.require_self_verifying_certificate or certificate.self_verifying
        latency = (time.perf_counter_ns() - start) / 1_000_000
        return VerifiedTileResponse(
            rgb,
            address,
            passed,
            False,
            certificate.mode,
            latency,
        )
    packet = McV1Reader(resolved).read_tile(address)
    if len(packet) < _PACKET_HEADER.size:
        raise ValueError("adapter packet is truncated")
    magic, kind, allocation_length, payload_length, repair_length, cert_length, method_length = _PACKET_HEADER.unpack_from(packet)
    if magic != b"SVP2" or kind not in (0, 1):
        raise ValueError("adapter packet identity is unsupported")
    offset = _PACKET_HEADER.size + method_length + (1 if kind == 0 else 0)
    expected = offset + allocation_length + payload_length + repair_length + cert_length
    if expected != len(packet):
        raise ValueError("adapter packet layout is invalid")
    allocation_map = packet[offset : offset + allocation_length]
    payload_offset = offset + allocation_length
    candidate_payload = packet[payload_offset : payload_offset + payload_length]
    repair_offset = payload_offset + payload_length
    repair_payload = packet[repair_offset : repair_offset + repair_length]
    certificate_payload = packet[-cert_length:]
    if kind == 0:
        rgb = SharedLosslessCodec().decode(
            candidate_payload, (address.height, address.width, 3)
        )
    else:
        rgb = decode_candidate(candidate_payload, allocation_map)
    if repair_payload:
        rgb = apply_repair_packet(rgb, repair_payload)
    certificate = decode_certificate(certificate_payload)
    packet_bound = (
        hashlib.sha256(allocation_map + candidate_payload + repair_payload).hexdigest()
        == certificate.packet_sha256
    )
    verification = verify_certificate(rgb, certificate, selected_contract.acceptance)
    passed = packet_bound and verification.passed
    if selected_contract.require_self_verifying_certificate:
        passed = passed and certificate.self_verifying
    latency = (time.perf_counter_ns() - start) / 1_000_000
    return VerifiedTileResponse(
        rgb,
        address,
        passed,
        False,
        certificate.mode,
        latency,
    )
