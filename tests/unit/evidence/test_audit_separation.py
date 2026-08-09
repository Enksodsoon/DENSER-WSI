from __future__ import annotations

import inspect

import numpy as np

from denser.evidence.architecture import compare_acceptance
from denser.evidence.audit import AuditProfile, compute_audit_evidence
from denser.evidence.boundary import compute_allocation_features


def test_audit_features_cannot_enter_allocation_or_acceptance_selection() -> None:
    assert "audit" not in inspect.signature(compute_allocation_features).parameters
    assert "audit" not in inspect.signature(compare_acceptance).parameters


def test_audit_evidence_has_separate_type_and_namespace() -> None:
    rgb = np.full((8, 8, 3), 128, dtype=np.uint8)
    evidence = compute_audit_evidence(rgb, AuditProfile())
    assert type(evidence).__name__ == "AuditEvidence"
    assert evidence.version.startswith("AUDIT-")
    assert len(evidence.sha256) == 64
