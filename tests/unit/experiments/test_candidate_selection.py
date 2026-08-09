from __future__ import annotations

import numpy as np
import denser.experiments.candidate_selection as selection_module

from denser.certificates.encode import decode_certificate
from denser.certificates.verify import verify_certificate
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry
from denser.container.packet_v2 import HEADER as TILE_PACKET_HEADER
from denser.container.packet_v2 import McV2TilePacket
from denser.core.models import ByteBreakdown
from denser.evidence.localized import LocalizedAcceptanceResult, LocalizedAcceptanceVerifier
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.experiments.candidate_selection import (
    choose_smallest_accepted_result,
    prepare_candidate_selection,
    select_smallest_accepted_candidate,
)


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


def test_extension_portfolio_retains_smaller_baseline_result() -> None:
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    contract = AcceptanceContract()
    grid = PhysicalGrid(0.25, 0.25)
    registry = CodecRegistry()
    registry.register("fixture", lambda payload, allocation, shape, profile: source.copy())
    small = select_smallest_accepted_candidate(
        source, [_candidate("baseline", b"x")], registry, contract, grid, cell_size_px=8
    )
    large = select_smallest_accepted_candidate(
        source,
        [_candidate("extension", b"x" * 128)],
        registry,
        contract,
        grid,
        cell_size_px=8,
    )
    assert choose_smallest_accepted_result(small, large) is small
    assert choose_smallest_accepted_result(large, small) is small


def test_extension_portfolio_reuses_bound_fallback_and_incumbent(monkeypatch) -> None:
    source = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    contract = AcceptanceContract()
    grid = PhysicalGrid(0.25, 0.25)
    prepared = LocalizedAcceptanceVerifier(contract, 8, grid).prepare(source)
    encode_calls = 0
    real_encode = SharedLosslessCodec.encode

    def counted_encode(self, pixels):  # type: ignore[no-untyped-def]
        nonlocal encode_calls
        encode_calls += 1
        return real_encode(self, pixels)

    monkeypatch.setattr(SharedLosslessCodec, "encode", counted_encode)
    context = prepare_candidate_selection(
        source, contract, grid, cell_size_px=8, prepared_verifier=prepared
    )
    registry = CodecRegistry()
    registry.register("fixture", lambda payload, allocation, shape, profile: source.copy())
    standard = select_smallest_accepted_candidate(
        source,
        [_candidate("standard", b"s" * 16)],
        registry,
        contract,
        grid,
        cell_size_px=8,
        prepared_verifier=prepared,
        prepared_selection=context,
    )
    extended = select_smallest_accepted_candidate(
        source,
        [_candidate("extension", b"x")],
        registry,
        contract,
        grid,
        cell_size_px=8,
        prepared_verifier=prepared,
        prepared_selection=context,
        incumbent=standard,
    )
    assert encode_calls == 1
    assert extended.candidate.profile_id == "extension"


def test_prepared_selection_rejects_a_different_source() -> None:
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    contract = AcceptanceContract()
    grid = PhysicalGrid(0.25, 0.25)
    prepared = LocalizedAcceptanceVerifier(contract, 8, grid).prepare(source)
    context = prepare_candidate_selection(
        source, contract, grid, cell_size_px=8, prepared_verifier=prepared
    )
    with np.testing.assert_raises_regex(ValueError, "prepared selection source"):
        select_smallest_accepted_candidate(
            np.ones_like(source),
            [],
            CodecRegistry(),
            contract,
            grid,
            cell_size_px=8,
            prepared_selection=context,
        )


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


def test_exact_candidate_does_not_run_localized_comparison(monkeypatch) -> None:
    source = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    contract = AcceptanceContract()
    grid = PhysicalGrid(0.25, 0.25)
    prepared = LocalizedAcceptanceVerifier(contract, 8, grid).prepare(source)

    def unexpected(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("exact candidates do not require localized comparison")

    monkeypatch.setattr(type(prepared), "prepare_cells", unexpected)
    monkeypatch.setattr(type(prepared), "verify", unexpected)
    registry = CodecRegistry()
    registry.register("fixture", lambda payload, allocation, shape, profile: source.copy())
    selected = select_smallest_accepted_candidate(
        source,
        [_candidate("exact", b"x")],
        registry,
        contract,
        grid,
        cell_size_px=8,
        prepared_verifier=prepared,
    )
    assert selected.candidate.profile_id == "exact"


def test_selection_reuses_prepared_evidence_for_certificate_builds(monkeypatch) -> None:
    source = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    contract = AcceptanceContract()
    grid = PhysicalGrid(0.25, 0.25)
    prepared = LocalizedAcceptanceVerifier(contract, 8, grid).prepare(source)
    real_build = selection_module.build_certificate
    evidence_arguments = []

    def capture(*args, **kwargs):  # type: ignore[no-untyped-def]
        evidence_arguments.append(
            (kwargs.get("reference_evidence"), kwargs.get("decoded_evidence"))
        )
        return real_build(*args, **kwargs)

    monkeypatch.setattr(selection_module, "build_certificate", capture)
    registry = CodecRegistry()
    registry.register("fixture", lambda payload, allocation, shape, profile: source.copy())
    select_smallest_accepted_candidate(
        source,
        [_candidate("exact", b"x")],
        registry,
        contract,
        grid,
        cell_size_px=8,
        prepared_verifier=prepared,
    )
    assert evidence_arguments
    assert all(reference is prepared.reference_evidence for reference, _ in evidence_arguments)
    assert all(decoded is prepared.reference_evidence for _, decoded in evidence_arguments)


def test_selection_reuses_verified_lossy_evidence_for_certificate(monkeypatch) -> None:
    source = np.full((16, 16, 3), 120, dtype=np.uint8)
    decoded = source.copy()
    decoded[0, 0, 0] = 121
    contract = AcceptanceContract(
        nuclear_relative_tolerance=1e9,
        architecture_relative_tolerance=1e9,
        sentinel_relative_tolerance=1e9,
        visual_relative_tolerance=1e9,
    )
    grid = PhysicalGrid(0.25, 0.25)
    prepared = LocalizedAcceptanceVerifier(contract, 8, grid).prepare(source)
    evidence_calls = 0
    real_evidence_for = type(prepared).evidence_for

    def counted(self, pixels):  # type: ignore[no-untyped-def]
        nonlocal evidence_calls
        evidence_calls += 1
        return real_evidence_for(self, pixels)

    monkeypatch.setattr(type(prepared), "evidence_for", counted)

    def accepted(self, original, pixels):  # type: ignore[no-untyped-def]
        self.evidence_for(pixels)
        return LocalizedAcceptanceResult(True, ())

    monkeypatch.setattr(type(prepared), "verify", accepted)
    registry = CodecRegistry()
    registry.register("fixture", lambda payload, allocation, shape, profile: decoded.copy())
    select_smallest_accepted_candidate(
        source,
        [_candidate("lossy", b"x")],
        registry,
        contract,
        grid,
        cell_size_px=8,
        prepared_verifier=prepared,
    )
    assert evidence_calls >= 3


def test_standard_portfolio_uses_frozen_jpeg90_as_initial_byte_bound() -> None:
    source = np.random.default_rng(40).integers(0, 256, (16, 16, 3), dtype=np.uint8)
    calls: list[str] = []
    registry = CodecRegistry()

    def decode(payload, allocation, shape, profile):  # type: ignore[no-untyped-def]
        calls.append(profile)
        return source.copy() if profile in {"jpeg-q90-444-opt", "smaller-pass"} else np.zeros(shape, dtype=np.uint8)

    registry.register("jpeg", decode)
    candidates = [
        EncodedCandidate("jpeg", "small-fail", b"a", ByteBreakdown(payload=1)),
        EncodedCandidate("jpeg", "smaller-pass", b"b" * 8, ByteBreakdown(payload=8)),
        EncodedCandidate("jpeg", "jpeg-q90-444-opt", b"c" * 32, ByteBreakdown(payload=32)),
        EncodedCandidate("jpeg", "large", b"d" * 64, ByteBreakdown(payload=64)),
    ]
    selected = select_smallest_accepted_candidate(
        source,
        candidates,
        registry,
        AcceptanceContract(0.0, 0.0, 0.0, 0.0),
        PhysicalGrid(0.25, 0.25),
        cell_size_px=8,
    )
    assert calls[0] == "jpeg-q90-444-opt"
    assert selected.candidate.profile_id == "smaller-pass"


def test_parallel_candidate_evaluation_is_deterministic_and_matches_serial() -> None:
    source = np.random.default_rng(77).integers(0, 256, (16, 16, 3), dtype=np.uint8)
    registry = CodecRegistry()
    registry.register(
        "fixture",
        lambda payload, allocation, shape, profile: (
            source.copy() if profile in {"accepted-a", "accepted-b"} else np.zeros(shape, dtype=np.uint8)
        ),
    )
    candidates = [
        _candidate("rejected", b"r"),
        _candidate("accepted-b", b"b" * 16),
        _candidate("accepted-a", b"a" * 8),
    ]
    arguments = (
        source,
        candidates,
        registry,
        AcceptanceContract(),
        PhysicalGrid(0.25, 0.25),
    )
    serial = select_smallest_accepted_candidate(*arguments, cell_size_px=8)
    parallel = select_smallest_accepted_candidate(
        *arguments, cell_size_px=8, max_candidate_workers=3
    )
    repeated = select_smallest_accepted_candidate(
        *arguments, cell_size_px=8, max_candidate_workers=3
    )
    assert parallel.candidate.profile_id == serial.candidate.profile_id
    assert parallel.packet == serial.packet == repeated.packet
