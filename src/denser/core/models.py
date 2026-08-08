from __future__ import annotations

import re
from dataclasses import dataclass


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True, order=True)
class TileAddress:
    level: int
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("level", "x", "y"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("width", "height"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class SlideIdentity:
    research_id: str
    source_sha256: str
    case_group_sha256: str

    def __post_init__(self) -> None:
        if not self.research_id.strip():
            raise ValueError("research_id must not be empty")
        for name in ("source_sha256", "case_group_sha256"):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ByteBreakdown:
    payload: int = 0
    repair: int = 0
    certificate: int = 0
    reference_evidence: int = 0
    index: int = 0
    integrity: int = 0
    overview: int = 0
    metadata: int = 0
    padding: int = 0
    header: int = 0
    method_signaling: int = 0
    fallback_signaling: int = 0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def complete(self) -> int:
        return sum(getattr(self, name) for name in self.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class MethodResult:
    method_id: str
    profile_id: str
    status: str
    breakdown: ByteBreakdown

    def __post_init__(self) -> None:
        for name in ("method_id", "profile_id", "status"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")

    @property
    def complete_bytes(self) -> int:
        return self.breakdown.complete
