from __future__ import annotations

import numpy as np

from denser.certificates.encode import decode_certificate
from denser.certificates.verify import verify_certificate
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry
from denser.container.packet_v2 import McV2TilePacket
from denser.core.models import ByteBreakdown
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
