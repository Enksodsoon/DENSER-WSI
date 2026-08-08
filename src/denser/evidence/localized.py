from __future__ import annotations

from dataclasses import dataclass
import hashlib
from dataclasses import field

import numpy as np

from denser.evidence.architecture import (
    compare_evidence,
    compute_acceptance_evidence,
)
from denser.evidence.types import AcceptanceContract, AcceptanceEvidence, PhysicalGrid
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
        return self.prepare(source).verify(source, decoded)

    def prepare(self, source: np.ndarray) -> PreparedLocalizedAcceptanceVerifier:
        original = np.asarray(source)
        if original.dtype != np.uint8 or original.ndim != 3 or original.shape[2] != 3:
            raise ValueError("localized acceptance requires uint8 RGB source")
        return PreparedLocalizedAcceptanceVerifier(
            self.contract,
            self.cell_size_px,
            self.physical_grid,
            original,
            hashlib.sha256(original.tobytes(order="C")).hexdigest(),
            compute_acceptance_evidence(original, self.physical_grid, self.contract),
        )


@dataclass(slots=True)
class PreparedLocalizedAcceptanceVerifier:
    contract: AcceptanceContract
    cell_size_px: int
    physical_grid: PhysicalGrid
    _source: np.ndarray
    _source_sha256: str
    _reference: AcceptanceEvidence
    _cell_references: dict[tuple[int, int, int, int], AcceptanceEvidence] = field(
        default_factory=dict
    )

    def verify(self, source: np.ndarray, decoded: np.ndarray) -> LocalizedAcceptanceResult:
        original = np.asarray(source)
        candidate = np.asarray(decoded)
        if original.dtype != np.uint8 or candidate.dtype != np.uint8 or original.shape != candidate.shape:
            raise ValueError("localized acceptance requires matching uint8 RGB tiles")
        if original is not self._source and hashlib.sha256(
            original.tobytes(order="C")
        ).hexdigest() != self._source_sha256:
            raise ValueError("prepared verifier source does not match bound source")
        candidate_evidence = compute_acceptance_evidence(
            candidate, self.physical_grid, self.contract
        )
        comparison = compare_evidence(self._reference, candidate_evidence, self.contract)
        if not comparison.failed_groups:
            return LocalizedAcceptanceResult(True, ())
        height, width, _ = original.shape
        failures: list[RepairFailure] = []
        for y in range(0, height, self.cell_size_px):
            for x in range(0, width, self.cell_size_px):
                cell_height = min(self.cell_size_px, height - y)
                cell_width = min(self.cell_size_px, width - x)
                key = (x, y, cell_width, cell_height)
                reference = self._cell_references.get(key)
                if reference is None:
                    reference = compute_acceptance_evidence(
                        original[y : y + cell_height, x : x + cell_width],
                        self.physical_grid,
                        self.contract,
                    )
                    self._cell_references[key] = reference
                cell = compare_evidence(
                    reference,
                    compute_acceptance_evidence(
                        candidate[y : y + cell_height, x : x + cell_width],
                        self.physical_grid,
                        self.contract,
                    ),
                    self.contract,
                )
                if cell.failed_groups:
                    failures.append(RepairFailure(x, y, cell_width, cell_height, width, height))
        if not failures:
            failures.append(RepairFailure(0, 0, width, height, width, height))
        return LocalizedAcceptanceResult(False, tuple(failures))
