"""Deterministic sparse repair and fail-closed escalation."""

from denser.repair.escalate import RepairResult, repair_until_verified
from denser.repair.mask import RepairFailure, RepairMask, build_union_repair_mask

__all__ = [
    "RepairFailure",
    "RepairMask",
    "RepairResult",
    "build_union_repair_mask",
    "repair_until_verified",
]

