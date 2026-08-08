from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from denser.evidence.architecture import compare_acceptance
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.repair.mask import RepairFailure


@dataclass(frozen=True, slots=True)
class LocalizedAcceptanceResult:
    passed: bool
    failures: tuple[RepairFailure, ...]


@dataclass(frozen=True, slots=True)
class LocalizedAcceptanceVerifier:
    contract: AcceptanceContract
    cell_size_px: int
    physical_grid: PhysicalGrid = PhysicalGrid(0.25, 0.25)

    def __post_init__(self) -> None:
        if self.cell_size_px <= 0:
            raise ValueError("acceptance cell size must be positive")

    def verify(self, source: np.ndarray, decoded: np.ndarray) -> LocalizedAcceptanceResult:
        original = np.asarray(source)
        candidate = np.asarray(decoded)
        if original.dtype != np.uint8 or candidate.dtype != np.uint8 or original.shape != candidate.shape:
            raise ValueError("localized acceptance requires matching uint8 RGB tiles")
        comparison = compare_acceptance(original, candidate, self.physical_grid, self.contract)
        if not comparison.failed_groups:
            return LocalizedAcceptanceResult(True, ())
        height, width, _ = original.shape
        failures: list[RepairFailure] = []
        for y in range(0, height, self.cell_size_px):
            for x in range(0, width, self.cell_size_px):
                cell_height = min(self.cell_size_px, height - y)
                cell_width = min(self.cell_size_px, width - x)
                cell = compare_acceptance(
                    original[y : y + cell_height, x : x + cell_width],
                    candidate[y : y + cell_height, x : x + cell_width],
                    self.physical_grid,
                    self.contract,
                )
                if cell.failed_groups:
                    failures.append(RepairFailure(x, y, cell_width, cell_height, width, height))
        if not failures:
            failures.append(RepairFailure(0, 0, width, height, width, height))
        return LocalizedAcceptanceResult(False, tuple(failures))
