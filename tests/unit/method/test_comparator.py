from __future__ import annotations

import numpy as np

from denser.method.candidates import (
    CandidateProfile,
    build_denser_candidates,
    build_uniform_candidates,
    decode_transform_candidate,
)


def _rgb() -> np.ndarray:
    y, x = np.mgrid[:16, :16]
    return np.stack((x * 10, y * 10, (x + y) * 5), axis=2).astype(np.uint8)


def test_uniform_and_denser_share_basis_entropy_and_candidate_count() -> None:
    profile = CandidateProfile(quantization_steps=(2.0, 4.0, 8.0))
    uniform = build_uniform_candidates(_rgb(), profile)
    denser = build_denser_candidates(_rgb(), np.ones_like(_rgb(), dtype=np.float64), profile)
    assert [candidate.basis_id for candidate in uniform] == [candidate.basis_id for candidate in denser]
    assert [candidate.entropy_model_id for candidate in uniform] == [candidate.entropy_model_id for candidate in denser]
    assert len(uniform) == len(denser)


def test_transform_candidate_round_trip_contract_and_determinism() -> None:
    profile = CandidateProfile(quantization_steps=(1.0,))
    first = build_uniform_candidates(_rgb(), profile)[0]
    second = build_uniform_candidates(_rgb().copy(), profile)[0]
    assert first.payload == second.payload
    decoded = decode_transform_candidate(first.payload)
    assert decoded.shape == _rgb().shape
    assert decoded.dtype == np.uint8


def test_denser_weighting_changes_packet_but_not_coder_identity() -> None:
    profile = CandidateProfile(quantization_steps=(8.0,))
    sensitivity = np.ones_like(_rgb(), dtype=np.float64)
    sensitivity[:, :8] = 100.0
    uniform = build_uniform_candidates(_rgb(), profile)[0]
    denser = build_denser_candidates(_rgb(), sensitivity, profile)[0]
    assert uniform.payload != denser.payload
    assert uniform.basis_id == denser.basis_id
    assert uniform.entropy_model_id == denser.entropy_model_id


def test_matched_entropy_model_uses_versioned_fixed_level_six() -> None:
    candidate = build_uniform_candidates(_rgb(), CandidateProfile((2.0,)))[0]
    assert candidate.entropy_model_id == "int32-zlib-fixed-level6-v2"
