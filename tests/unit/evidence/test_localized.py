from __future__ import annotations

import numpy as np
import pytest

from denser.evidence.localized import LocalizedAcceptanceVerifier
from denser.evidence.types import AcceptanceContract, AcceptanceEvidence


def test_localized_verifier_returns_bounded_failed_cells() -> None:
    source = np.full((16, 16, 3), 180, dtype=np.uint8)
    source[2:6, 2:6, 0] = 20
    decoded = source.copy()
    decoded[:8, :8] = 255
    verifier = LocalizedAcceptanceVerifier(
        AcceptanceContract(0.01, 0.01, 0.001, 0.01), cell_size_px=8
    )
    result = verifier.verify(source, decoded)
    assert not result.passed
    assert result.failures
    assert all(item.width <= 8 and item.height <= 8 for item in result.failures)
    assert any(item.x == 0 and item.y == 0 for item in result.failures)
    assert all(item.failed_groups for item in result.failures)


def test_localized_verifier_accepts_identical_pixels() -> None:
    source = np.full((8, 8, 3), 100, dtype=np.uint8)
    result = LocalizedAcceptanceVerifier(AcceptanceContract(), 8).verify(source, source.copy())
    assert result.passed
    assert result.failures == ()


def test_prepared_verifier_matches_direct_result_and_binds_source() -> None:
    source = np.full((16, 16, 3), 180, dtype=np.uint8)
    source[2:6, 2:6] = (20, 20, 20)
    decoded = source.copy()
    decoded[:8, :8] = 255
    verifier = LocalizedAcceptanceVerifier(
        AcceptanceContract(0.01, 0.01, 0.001, 0.01), 8
    )
    prepared = verifier.prepare(source)
    assert prepared.verify(source, decoded) == verifier.verify(source, decoded)
    different = source.copy()
    different[-1, -1] = 0
    with pytest.raises(ValueError, match="source"):
        prepared.verify(different, decoded)


def test_tile_average_cannot_bypass_cell_level_acceptance(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    source = np.zeros((16, 16, 3), dtype=np.uint8)
    decoded = source.copy()
    decoded[:8, :8] = 255

    def fake_evidence(rgb, grid, contract, *, groups=None):  # type: ignore[no-untyped-def]
        value = 0.0 if rgb.shape[0] == 16 else float(np.asarray(rgb).mean() / 255)
        return AcceptanceEvidence(contract.version, (("visual", (value,)),), "0" * 64)

    monkeypatch.setattr("denser.evidence.localized.compute_acceptance_evidence", fake_evidence)
    result = LocalizedAcceptanceVerifier(AcceptanceContract(), 8).verify(source, decoded)
    assert not result.passed
    assert any(item.x == 0 and item.y == 0 for item in result.failures)


def test_incremental_repair_verification_matches_full_reverification() -> None:
    source = np.random.default_rng(31).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    proposal = source.copy()
    proposal[:16, :16] = 255
    proposal[32:48, 32:48] = 0
    verifier = LocalizedAcceptanceVerifier(
        AcceptanceContract(0.01, 0.01, 0.001, 0.01), 16
    ).prepare(source)
    initial = verifier.verify(source, proposal)
    repaired = proposal.copy()
    repaired[:16, :16] = source[:16, :16]
    changed = np.any(repaired != proposal, axis=2)
    assert verifier.verify_changed(source, repaired, initial, changed) == verifier.verify(
        source, repaired
    )
