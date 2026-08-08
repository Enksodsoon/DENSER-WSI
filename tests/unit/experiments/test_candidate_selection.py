from __future__ import annotations

import numpy as np

from denser.certificates.encode import decode_certificate
from denser.certificates.verify import verify_certificate
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry
from denser.container.packet_v2 import HEADER as TILE_PACKET_HEADER
from denser.container.packet_v2 import McV2TilePacket
from denser.core.models import ByteBreakdown
from denser.evidence.localized import LocalizedAcceptanceVerifier
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.experiments.candidate_selection import select_smallest_accepted_candidate


def _candidate(profile: str, payload: bytes) -> EncodedCandidate:
    return EncodedCandidate("fixture", profile, payload, ByteBreakdown(payload=len(payload)))


def test_selection_uses_smallest_complete_accepted_mcv2_packet() -> None:
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    decoded = {b"small": np.full_like(source, 255), b"accepted-payload": source.copy()}
    registry = CodecRegistry()
    registry.register("fixture", lambda payload, allocation, shape, profile: decoded[payload])
    selected = select_smallest_accepted_candidate(
        source,
        [_candidate("rejected", b"small"), _candidate("accepted", b"accepted-payload")],
        registry,
        AcceptanceContract(),
        PhysicalGrid(0.25, 0.25),
        cell_size_px=8,
    )
    assert selected.candidate.profile_id == "accepted"
    packet = McV2TilePacket.decode(selected.packet)
    certificate = decode_certificate(packet.certificate)
    assert verify_certificate(selected.decoded, certificate, AcceptanceContract()).passed
    assert selected.breakdown.complete == len(selected.packet)


def test_selection_falls_back_when_no_candidate_beats_verified_lossless() -> None:
    source = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    registry = CodecRegistry()
    registry.register(
        "fixture", lambda payload, allocation, shape, profile: np.zeros(shape, dtype=np.uint8)
    )
    selected = select_smallest_accepted_candidate(
        source,
        [_candidate("bad", b"x" * 1000)],
        registry,
        AcceptanceContract(0.0, 0.0, 0.0, 0.0),
        PhysicalGrid(0.25, 0.25),
        cell_size_px=8,
    )
    assert selected.candidate.codec_id == SharedLosslessCodec.codec_id
    assert selected.status == "fallback"
    assert McV2TilePacket.decode(selected.packet).fallback


def test_selection_skips_candidates_whose_bytes_cannot_beat_current_best() -> None:
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    calls: list[str] = []
    registry = CodecRegistry()

    def decode(payload, allocation, shape, profile):  # type: ignore[no-untyped-def]
        calls.append(profile)
        return source.copy()

    registry.register("fixture", decode)
    selected = select_smallest_accepted_candidate(
        source,
        [_candidate("huge", b"x" * 100_000), _candidate("small", b"x")],
        registry,
        AcceptanceContract(),
        PhysicalGrid(0.25, 0.25),
        cell_size_px=8,
    )
    assert selected.breakdown.complete == len(selected.packet)
    assert "huge" not in calls


def test_selection_counts_unavoidable_certificate_bytes_before_decoding() -> None:
    source = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    contract = AcceptanceContract()
    grid = PhysicalGrid(0.25, 0.25)
    baseline = select_smallest_accepted_candidate(
        source, [], CodecRegistry(), contract, grid, cell_size_px=8
    )
    calls = 0
    registry = CodecRegistry()

    def decode(payload, allocation, shape, profile):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return source.copy()

    registry.register("fixture", decode)
    identity_bytes = len("fixture".encode("ascii")) + len("near".encode("ascii"))
    old_bound_payload = max(
        1, baseline.breakdown.complete - TILE_PACKET_HEADER.size - identity_bytes - 1
    )
    select_smallest_accepted_candidate(
        source,
        [_candidate("near", b"x" * old_bound_payload)],
        registry,
        contract,
        grid,
        cell_size_px=8,
    )
    assert calls == 0


def test_selection_reuses_only_a_matching_prepared_source_verifier() -> None:
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    contract = AcceptanceContract()
    grid = PhysicalGrid(0.25, 0.25)
    prepared = LocalizedAcceptanceVerifier(contract, 8, grid).prepare(source)
    registry = CodecRegistry()
    registry.register("fixture", lambda payload, allocation, shape, profile: source.copy())
    selected = select_smallest_accepted_candidate(
        source,
        [_candidate("accepted", b"x")],
        registry,
        contract,
        grid,
        cell_size_px=8,
        prepared_verifier=prepared,
    )
    assert selected.candidate.profile_id == "accepted"

    with np.testing.assert_raises_regex(ValueError, "prepared verifier configuration"):
        select_smallest_accepted_candidate(
            source,
            [_candidate("accepted", b"x")],
            registry,
            AcceptanceContract(visual_relative_tolerance=0.5),
            grid,
            cell_size_px=8,
            prepared_verifier=prepared,
        )
