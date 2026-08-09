from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from denser.certificates.encode import build_certificate, decode_certificate, encode_certificate
from denser.certificates.verify import (
    verify_certificate,
    verify_encoder_certificate_with_evidence,
)
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry
from denser.container.packet_v2 import HEADER as TILE_PACKET_HEADER
from denser.container.packet_v2 import McV2TilePacket
from denser.core.canonical import canonical_json_bytes
from denser.core.models import ByteBreakdown
from denser.evidence.localized import (
    LocalizedAcceptanceVerifier,
    PreparedLocalizedAcceptanceVerifier,
)
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


@dataclass(frozen=True, slots=True)
class PreparedCandidateSelection:
    source_sha256: str
    contract: AcceptanceContract
    grid: PhysicalGrid
    cell_size_px: int
    verifier: PreparedLocalizedAcceptanceVerifier
    fallback_codec: SharedLosslessCodec
    fallback_candidate: EncodedCandidate
    fallback_decoded: np.ndarray
    fallback_result: AcceptedTileCandidate


def choose_smallest_accepted_result(
    *results: AcceptedTileCandidate,
) -> AcceptedTileCandidate:
    if not results:
        raise ValueError("accepted-result comparison requires at least one result")
    return min(
        results,
        key=lambda result: (
            result.breakdown.complete,
            result.candidate.codec_id,
            result.candidate.profile_id,
        ),
    )


def _packet_for(
    source: np.ndarray,
    candidate: EncodedCandidate,
    decoded: np.ndarray,
    repair_payload: bytes,
    contract: AcceptanceContract,
    grid: PhysicalGrid,
    *,
    fallback: bool,
    prepared_verifier: PreparedLocalizedAcceptanceVerifier,
) -> tuple[bytes, ByteBreakdown]:
    decoded_evidence = prepared_verifier.evidence_for(decoded)
    certificate = build_certificate(
        source,
        candidate,
        contract,
        physical_grid=grid,
        decoded_rgb=decoded,
        repair_payload=repair_payload,
        reference_evidence=prepared_verifier.reference_evidence,
        decoded_evidence=decoded_evidence,
    )
    if not verify_encoder_certificate_with_evidence(
        decoded, certificate, contract, decoded_evidence
    ).passed:
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


def prepare_candidate_selection(
    source_rgb: np.ndarray,
    contract: AcceptanceContract,
    grid: PhysicalGrid,
    *,
    cell_size_px: int,
    prepared_verifier: PreparedLocalizedAcceptanceVerifier | None = None,
) -> PreparedCandidateSelection:
    source = np.asarray(source_rgb)
    if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("candidate selection requires a uint8 RGB tile")
    verifier = prepared_verifier or LocalizedAcceptanceVerifier(
        contract, cell_size_px, grid
    ).prepare(source)
    if (
        verifier.contract != contract
        or verifier.cell_size_px != cell_size_px
        or verifier.physical_grid != grid
    ):
        raise ValueError("prepared verifier configuration does not match selection")
    source_sha256 = hashlib.sha256(source.tobytes(order="C")).hexdigest()
    if source_sha256 != verifier.source_sha256:
        raise ValueError("prepared verifier source does not match selection")
    fallback_codec = SharedLosslessCodec()
    fallback = fallback_codec.encode(source)
    fallback_decoded = fallback_codec.decode(fallback.payload, source.shape)
    fallback_packet, fallback_breakdown = _packet_for(
        source,
        fallback,
        fallback_decoded,
        b"",
        contract,
        grid,
        fallback=True,
        prepared_verifier=verifier,
    )
    fallback_result = AcceptedTileCandidate(
        fallback,
        fallback_decoded,
        b"",
        fallback_packet,
        fallback_breakdown,
        "fallback",
        (),
    )
    return PreparedCandidateSelection(
        source_sha256,
        contract,
        grid,
        cell_size_px,
        verifier,
        fallback_codec,
        fallback,
        fallback_decoded,
        fallback_result,
    )


def select_smallest_accepted_candidate(
    source_rgb: np.ndarray,
    candidates: list[EncodedCandidate],
    registry: CodecRegistry,
    contract: AcceptanceContract,
    grid: PhysicalGrid,
    *,
    cell_size_px: int,
    halo_um: float = 2.0,
    prepared_verifier: PreparedLocalizedAcceptanceVerifier | None = None,
    prepared_selection: PreparedCandidateSelection | None = None,
    incumbent: AcceptedTileCandidate | None = None,
    max_candidate_workers: int = 1,
) -> AcceptedTileCandidate:
    source = np.asarray(source_rgb)
    if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("candidate selection requires a uint8 RGB tile")
    if not 1 <= max_candidate_workers <= 6:
        raise ValueError("candidate workers must remain between one and six")
    if prepared_selection is not None:
        source_sha256 = hashlib.sha256(source.tobytes(order="C")).hexdigest()
        if source_sha256 != prepared_selection.source_sha256:
            raise ValueError("prepared selection source does not match selection")
        if (
            prepared_selection.contract != contract
            or prepared_selection.grid != grid
            or prepared_selection.cell_size_px != cell_size_px
        ):
            raise ValueError("prepared selection configuration does not match selection")
        if prepared_verifier is None:
            prepared_verifier = prepared_selection.verifier
        elif prepared_verifier is not prepared_selection.verifier:
            raise ValueError("prepared selection verifier does not match selection")
    if prepared_verifier is None:
        prepared_verifier = LocalizedAcceptanceVerifier(
            contract, cell_size_px, grid
        ).prepare(source)
    elif (
        prepared_verifier.contract != contract
        or prepared_verifier.cell_size_px != cell_size_px
        or prepared_verifier.physical_grid != grid
    ):
        raise ValueError("prepared verifier configuration does not match selection")
    if prepared_selection is None:
        prepared_selection = prepare_candidate_selection(
            source,
            contract,
            grid,
            cell_size_px=cell_size_px,
            prepared_verifier=prepared_verifier,
        )
    fallback_codec = prepared_selection.fallback_codec
    accepted: list[tuple[int, str, AcceptedTileCandidate]] = []
    rejected: list[str] = list(incumbent.rejected_profiles) if incumbent else []
    fallback = prepared_selection.fallback_candidate
    fallback_decoded = prepared_selection.fallback_decoded
    fallback_result = prepared_selection.fallback_result
    fallback_packet = fallback_result.packet
    fallback_breakdown = fallback_result.breakdown
    best_complete_bytes = len(fallback_packet)
    if incumbent is not None:
        if (
            incumbent.decoded.dtype != np.uint8
            or incumbent.decoded.shape != source.shape
            or incumbent.breakdown.complete != len(incumbent.packet)
        ):
            raise ValueError("incumbent selection result is invalid")
        accepted.append((len(incumbent.packet), incumbent.candidate.profile_id, incumbent))
        best_complete_bytes = min(best_complete_bytes, len(incumbent.packet))
    fallback_identity_bytes = len(
        canonical_json_bytes(f"{fallback.codec_id}:{fallback.profile_id}")
    )

    def packet_lower_bound(candidate: EncodedCandidate) -> int:
        candidate_identity_bytes = len(
            canonical_json_bytes(f"{candidate.codec_id}:{candidate.profile_id}")
        )
        certificate_bytes = (
            fallback_breakdown.certificate
            - fallback_identity_bytes
            + candidate_identity_bytes
        )
        return (
            TILE_PACKET_HEADER.size
            + len(candidate.codec_id.encode("ascii"))
            + len(candidate.profile_id.encode("ascii"))
            + len(candidate.allocation_map)
            + len(candidate.payload)
            + certificate_bytes
        )

    ordered = sorted(candidates, key=lambda item: (packet_lower_bound(item), item.profile_id))
    initial_bound = next(
        (
            item
            for item in ordered
            if item.codec_id == "jpeg" and item.profile_id == "jpeg-q90-444-opt"
        ),
        None,
    )
    evaluation_order = (
        [initial_bound, *(item for item in ordered if item is not initial_bound)]
        if initial_bound is not None
        else ordered
    )
    def evaluate_candidate(
        candidate: EncodedCandidate, maximum_complete_bytes: int
    ) -> AcceptedTileCandidate | None:
        try:
            decoded = registry.decode(candidate, source.shape)
        except (OSError, RuntimeError, ValueError):
            return None
        repair_payload = b""
        status = "verified"
        exact = np.array_equal(source, decoded)
        if not exact:
            verification = prepared_verifier.verify(source, decoded)
        if not exact and not verification.passed:
            repair = repair_until_verified(
                source,
                decoded,
                prepared_verifier,
                fallback_codec,
                halo_um=halo_um,
                mpp=grid.mean_mpp,
                initial_verification=verification,
                encoded_fallback=fallback,
                fallback_decoded=fallback_decoded,
                maximum_repair_bytes=max(
                    0, maximum_complete_bytes - packet_lower_bound(candidate)
                ),
            )
            if repair.status != "verified_repair":
                return None
            decoded = repair.decoded
            repair_payload = repair.payload
            status = repair.status
        packet, breakdown = _packet_for(
            source,
            candidate,
            decoded,
            repair_payload,
            contract,
            grid,
            fallback=False,
            prepared_verifier=prepared_verifier,
        )
        return AcceptedTileCandidate(
            candidate, decoded, repair_payload, packet, breakdown, status, ()
        )

    if max_candidate_workers == 1:
        for index, candidate in enumerate(evaluation_order):
            if packet_lower_bound(candidate) > best_complete_bytes:
                if index == 0 and candidate is initial_bound:
                    continue
                break
            result = evaluate_candidate(candidate, best_complete_bytes)
            if result is None:
                rejected.append(candidate.profile_id)
                continue
            accepted.append((len(result.packet), candidate.profile_id, result))
            best_complete_bytes = min(best_complete_bytes, len(result.packet))
    else:
        eligible = [
            candidate
            for candidate in ordered
            if packet_lower_bound(candidate) <= best_complete_bytes
        ]
        if eligible:
            prepared_verifier.prepare_cells()
            with ThreadPoolExecutor(
                max_workers=min(max_candidate_workers, len(eligible))
            ) as pool:
                evaluated = list(
                    pool.map(
                        lambda candidate: evaluate_candidate(
                            candidate, best_complete_bytes
                        ),
                        eligible,
                    )
                )
            for candidate, result in zip(eligible, evaluated, strict=True):
                if result is None:
                    rejected.append(candidate.profile_id)
                else:
                    accepted.append((len(result.packet), candidate.profile_id, result))

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
