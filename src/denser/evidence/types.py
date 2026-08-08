from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PhysicalGrid:
    mpp_x: float
    mpp_y: float

    def __post_init__(self) -> None:
        if not 0.05 <= self.mpp_x <= 5.0 or not 0.05 <= self.mpp_y <= 5.0:
            raise ValueError("physical grid MPP is outside supported bounds")

    @property
    def mean_mpp(self) -> float:
        return (self.mpp_x + self.mpp_y) / 2


@dataclass(frozen=True, slots=True)
class EvidenceContract:
    version: str = "HE-V1-allocation-1"
    boundary_scales_um: tuple[float, ...] = (1.0, 2.0, 4.0)
    orientations_deg: tuple[float, ...] = (0.0, 45.0, 90.0, 135.0)
    chromatin_bands_cycles_um: tuple[tuple[float, float], ...] = (
        (0.10, 0.25),
        (0.25, 0.50),
        (0.50, 1.00),
    )
    physical_grid: PhysicalGrid = field(default_factory=lambda: PhysicalGrid(0.25, 0.25))


@dataclass(frozen=True, slots=True)
class AllocationEvidence:
    version: str
    features: tuple[tuple[str, float], ...]
    sha256: str

    def vector(self) -> tuple[float, ...]:
        return tuple(value for _name, value in self.features)


@dataclass(frozen=True, slots=True)
class AcceptanceContract:
    version: str = "HE-V1-acceptance-1"
    nuclear_relative_tolerance: float = 0.12
    architecture_relative_tolerance: float = 0.12
    sentinel_relative_tolerance: float = 0.01
    visual_relative_tolerance: float = 0.20


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    version: str
    groups: tuple[tuple[str, tuple[float, ...]], ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class AcceptanceComparison:
    distances: tuple[tuple[str, float], ...]
    failed_groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditEvidence:
    version: str
    features: tuple[tuple[str, float], ...]
    sha256: str
