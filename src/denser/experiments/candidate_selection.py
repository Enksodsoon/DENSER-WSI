from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from denser.certificates.encode import build_certificate, decode_certificate, encode_certificate
from denser.certificates.verify import verify_certificate
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry
from denser.container.packet_v2 import HEADER as TILE_PACKET_HEADER
from denser.container.packet_v2 import McV2TilePacket
from denser.core.models import ByteBreakdown
from denser.evidence.localized import LocalizedAcceptanceVerifier
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.repair.escalate import repair_until_verified
from denser.repair.packet_v2 import apply_repair_packet


@dataclass(frozen=True, slots=True)
class AcceptedTileCandidate:
    candidate: EncodedCandidate
    decoded: np.ndarray
    repair_payload: bytes
    packet: bytes
    breakdown: ByteBreakdown
    status: str
    rejected_profiles: tuple[str, ...]


def _packet_for(
    source: np.ndarray,
    candidate: EncodedCandidate,
    decoded: np.ndarray,
    repair_payload: bytes,
    contract: AcceptanceContract,
    grid: PhysicalGrid,
    *,
    fallback: bool,
) -> tuple[bytes, ByteBreakdown]:
    certificate = build_certificate(
        source,
        candidate,
        contract,
        physical_grid=grid,
        decoded_rgb=decoded,
        repair_payload=repair_payload,
    )
    if not verify_certificate(decoded, certificate, contract).passed:
        raise RuntimeError("encoder-created certificate failed immediate verification")
    tile_packet = McV2TilePacket(
        candidate.codec_id,
        candidate.profile_id,
        candidate.allocation_map,
        candidate.payload,
        repair_payload,
        encode_certificate(certificate),
        fallback,
    )
    encoded = tile_packet.encode()
    breakdown = tile_packet.breakdown()
    if breakdown.complete != len(encoded):
        raise RuntimeError("MC-V2 tile packet byte accounting mismatch")
    return encoded, breakdown


def select_smallest_accepted_candidate(
    source_rgb: np.ndarray,
    candidates: list[EncodedCandidate],
    registry: CodecRegistry,
    contract: AcceptanceContract,
    grid: PhysicalGrid,
    *,
    cell_size_px: int,
    halo_um: float = 2.0,
) -> AcceptedTileCandidate:
    source = np.asarray(source_rgb)
    if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("candidate selection requires a uint8 RGB tile")
    verifier = LocalizedAcceptanceVerifier(contract, cell_size_px, grid)
    prepared_verifier = verifier.prepare(source)
    fallback_codec = SharedLosslessCodec()
    accepted: list[tuple[int, str, AcceptedTileCandidate]] = []
    rejected: list[str] = []
    fallback = fallback_codec.encode(source)
    fallback_decoded = fallback_codec.decode(fallback.payload, source.shape)
    fallback_packet, fallback_breakdown = _packet_for(
        source, fallback, fallback_decoded, b"", contract, grid, fallback=True
    )
    best_complete_bytes = len(fallback_packet)

    def packet_lower_bound(candidate: EncodedCandidate) -> int:
        return (
            TILE_PACKET_HEADER.size
            + len(candidate.codec_id.encode("ascii"))
            + len(candidate.profile_id.encode("ascii"))
            + len(candidate.allocation_map)
            + len(candidate.payload)
            + 1  # MC-V2 requires a non-empty certificate.
        )

    ordered = sorted(candidates, key=lambda item: (packet_lower_bound(item), item.profile_id))
    for candidate in ordered:
        if packet_lower_bound(candidate) > best_complete_bytes:
            break
        try:
            decoded = registry.decode(candidate, source.shape)
        except (OSError, RuntimeError, ValueError):
            rejected.append(candidate.profile_id)
            continue
        verification = prepared_verifier.verify(source, decoded)
        repair_payload = b""
        status = "verified"
        if not verification.passed:
            repair = repair_until_verified(
                source,
                decoded,
                prepared_verifier,
                fallback_codec,
                halo_um=halo_um,
                mpp=grid.mean_mpp,
            )
            if repair.status != "verified_repair":
                rejected.append(candidate.profile_id)
                continue
            decoded = repair.decoded
            repair_payload = repair.payload
            status = repair.status
        packet, breakdown = _packet_for(
            source, candidate, decoded, repair_payload, contract, grid, fallback=False
        )
        result = AcceptedTileCandidate(
            candidate, decoded, repair_payload, packet, breakdown, status, ()
        )
        accepted.append((len(packet), candidate.profile_id, result))
        best_complete_bytes = min(best_complete_bytes, len(packet))

    fallback_result = AcceptedTileCandidate(
        fallback,
        fallback_decoded,
        b"",
        fallback_packet,
        fallback_breakdown,
        "fallback",
        tuple(rejected),
    )
    accepted.append((len(fallback_packet), fallback.profile_id, fallback_result))
    selected = min(accepted, key=lambda item: (item[0], item[1]))[2]
    return AcceptedTileCandidate(
        selected.candidate,
        selected.decoded,
        selected.repair_payload,
        selected.packet,
        selected.breakdown,
        selected.status,
        tuple(rejected),
    )


def decode_and_verify_tile_packet(
    encoded: bytes,
    shape: tuple[int, int, int],
    registry: CodecRegistry,
    contract: AcceptanceContract,
) -> np.ndarray:
    packet = McV2TilePacket.decode(encoded)
    candidate = EncodedCandidate(
        packet.codec_id,
        packet.profile_id,
        packet.payload,
        ByteBreakdown(payload=len(packet.payload), method_signaling=len(packet.allocation_map)),
        allocation_map=packet.allocation_map,
    )
    if packet.fallback and packet.codec_id != SharedLosslessCodec.codec_id:
        raise ValueError("MC-V2 fallback signal requires the shared lossless codec")
    if packet.codec_id == SharedLosslessCodec.codec_id:
        decoded = SharedLosslessCodec().decode(packet.payload, shape)
    else:
        decoded = registry.decode(candidate, shape)
    if packet.repair:
        decoded = apply_repair_packet(decoded, packet.repair)
    certificate = decode_certificate(packet.certificate)
    if certificate.packet_sha256 != hashlib.sha256(
        packet.allocation_map + packet.payload + packet.repair
    ).hexdigest():
        raise ValueError("MC-V2 certificate is not bound to packet sections")
    if not verify_certificate(decoded, certificate, contract).passed:
        raise ValueError("MC-V2 evidence certificate verification failed")
    return decoded
