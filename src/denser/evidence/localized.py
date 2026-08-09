from __future__ import annotations

from dataclasses import dataclass
import hashlib
from dataclasses import field

import numpy as np

from denser.evidence.architecture import (
    compare_acceptance_groups,
    compare_evidence,
    compute_acceptance_groups,
    compute_acceptance_evidence,
)
from denser.evidence.cell_batch import (
    CellAcceptanceBatch,
    compare_cell_acceptance_batches,
    compute_cell_acceptance_batch,
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
    _cell_batch_reference: CellAcceptanceBatch | None = None
    _cell_references: dict[
        tuple[int, int, int, int, tuple[str, ...]],
        tuple[tuple[str, tuple[float, ...]], ...],
    ] = field(
        default_factory=dict
    )
    _candidate_evidence: dict[str, AcceptanceEvidence] = field(default_factory=dict)

    @property
    def reference_evidence(self) -> AcceptanceEvidence:
        return self._reference

    @property
    def source_sha256(self) -> str:
        return self._source_sha256

    def evidence_for(self, decoded: np.ndarray) -> AcceptanceEvidence:
        candidate = np.asarray(decoded)
        if (
            candidate.dtype != np.uint8
            or candidate.ndim != 3
            or candidate.shape != self._source.shape
        ):
            raise ValueError("candidate evidence requires source-shaped uint8 RGB pixels")
        digest = hashlib.sha256(candidate.tobytes(order="C")).hexdigest()
        if digest == self._source_sha256:
            return self._reference
        evidence = self._candidate_evidence.get(digest)
        if evidence is None:
            evidence = compute_acceptance_evidence(
                candidate, self.physical_grid, self.contract
            )
            self._candidate_evidence[digest] = evidence
        return evidence

    def prepare_cells(self) -> PreparedLocalizedAcceptanceVerifier:
        acceptance_groups = tuple(name for name, _values in self._reference.groups)
        height, width, _ = self._source.shape
        if not self._cell_references and acceptance_groups == (
            "nuclear_objects",
            "architecture",
            "rare_event_sentinels",
            "visual",
        ):
            batch_height = height - height % self.cell_size_px
            batch_width = width - width % self.cell_size_px
            batched = (
                compute_cell_acceptance_batch(
                    self._source[:batch_height, :batch_width],
                    self.physical_grid,
                    self.cell_size_px,
                )
                if min(batch_height, batch_width) >= self.cell_size_px
                else None
            )
            if batched is not None:
                self._cell_batch_reference = batched
                for index, bounds in enumerate(batched.bounds):
                    self._cell_references[(*bounds, acceptance_groups)] = tuple(
                        (name, tuple(float(value) for value in values[index]))
                        for name, values in batched.groups
                    )
        for y in range(0, height, self.cell_size_px):
            for x in range(0, width, self.cell_size_px):
                cell_height = min(self.cell_size_px, height - y)
                cell_width = min(self.cell_size_px, width - x)
                key = (x, y, cell_width, cell_height, acceptance_groups)
                if key not in self._cell_references:
                    self._cell_references[key] = compute_acceptance_groups(
                        self._source[y : y + cell_height, x : x + cell_width],
                        self.physical_grid,
                        groups=acceptance_groups,
                    )
        return self

    def verify(self, source: np.ndarray, decoded: np.ndarray) -> LocalizedAcceptanceResult:
        original = np.asarray(source)
        candidate = np.asarray(decoded)
        if original.dtype != np.uint8 or candidate.dtype != np.uint8 or original.shape != candidate.shape:
            raise ValueError("localized acceptance requires matching uint8 RGB tiles")
        if original is not self._source and hashlib.sha256(
            original.tobytes(order="C")
        ).hexdigest() != self._source_sha256:
            raise ValueError("prepared verifier source does not match bound source")
        candidate_evidence = self.evidence_for(candidate)
        comparison = compare_evidence(self._reference, candidate_evidence, self.contract)
        self.prepare_cells()
        acceptance_groups = tuple(name for name, _values in self._reference.groups)
        candidate_batch = (
            compute_cell_acceptance_batch(
                candidate[
                    : max(
                        (y + height for _x, y, _width, height in self._cell_batch_reference.bounds),
                        default=0,
                    ),
                    : max(
                        (x + width for x, _y, width, _height in self._cell_batch_reference.bounds),
                        default=0,
                    ),
                ],
                self.physical_grid,
                self.cell_size_px,
            )
            if self._cell_batch_reference is not None
            and acceptance_groups
            == (
                "nuclear_objects",
                "architecture",
                "rare_event_sentinels",
                "visual",
            )
            else None
        )
        batched_failures = (
            compare_cell_acceptance_batches(
                self._cell_batch_reference, candidate_batch, self.contract
            )
            if self._cell_batch_reference is not None and candidate_batch is not None
            else None
        )
        height, width, _ = original.shape
        failures: list[RepairFailure] = []
        for y in range(0, height, self.cell_size_px):
            for x in range(0, width, self.cell_size_px):
                cell_height = min(self.cell_size_px, height - y)
                cell_width = min(self.cell_size_px, width - x)
                key = (x, y, cell_width, cell_height, acceptance_groups)
                reference = self._cell_references[key]
                batch_key = (x, y, cell_width, cell_height)
                failed_groups = (
                    batched_failures[batch_key]
                    if batched_failures is not None and batch_key in batched_failures
                    else compare_acceptance_groups(
                        reference,
                        compute_acceptance_groups(
                            candidate[y : y + cell_height, x : x + cell_width],
                            self.physical_grid,
                            groups=acceptance_groups,
                        ),
                        self.contract,
                    ).failed_groups
                )
                if failed_groups:
                    failures.append(
                        RepairFailure(
                            x,
                            y,
                            cell_width,
                            cell_height,
                            width,
                            height,
                            failed_groups,
                        )
                    )
        if not failures and comparison.failed_groups:
            failures.append(
                RepairFailure(
                    0,
                    0,
                    width,
                    height,
                    width,
                    height,
                    comparison.failed_groups,
                )
            )
        return LocalizedAcceptanceResult(not failures, tuple(failures))

    def verify_changed(
        self,
        source: np.ndarray,
        decoded: np.ndarray,
        previous: LocalizedAcceptanceResult,
        changed_pixels: np.ndarray,
    ) -> LocalizedAcceptanceResult:
        original = np.asarray(source)
        candidate = np.asarray(decoded)
        changed = np.asarray(changed_pixels)
        if (
            original.dtype != np.uint8
            or candidate.dtype != np.uint8
            or original.shape != candidate.shape
            or changed.dtype != np.bool_
            or changed.shape != original.shape[:2]
        ):
            raise ValueError("incremental acceptance requires matching pixels and change mask")
        if original is not self._source and hashlib.sha256(
            original.tobytes(order="C")
        ).hexdigest() != self._source_sha256:
            raise ValueError("prepared verifier source does not match bound source")
        if not np.any(changed):
            return previous
        height, width, _ = original.shape
        total_cells = (
            ((height + self.cell_size_px - 1) // self.cell_size_px)
            * ((width + self.cell_size_px - 1) // self.cell_size_px)
        )
        changed_bounds = {
            (x, y, min(self.cell_size_px, width - x), min(self.cell_size_px, height - y))
            for y in range(0, height, self.cell_size_px)
            for x in range(0, width, self.cell_size_px)
            if np.any(changed[y : y + self.cell_size_px, x : x + self.cell_size_px])
        }
        exact_source_bounds = {
            bounds
            for bounds in changed_bounds
            if np.array_equal(
                candidate[
                    bounds[1] : bounds[1] + bounds[3],
                    bounds[0] : bounds[0] + bounds[2],
                ],
                original[
                    bounds[1] : bounds[1] + bounds[3],
                    bounds[0] : bounds[0] + bounds[2],
                ],
            )
        }
        if (
            len(changed_bounds) >= max(4, (total_cells + 7) // 8)
            and changed_bounds != exact_source_bounds
        ):
            return self.verify(original, candidate)
        candidate_evidence = self.evidence_for(candidate)
        comparison = compare_evidence(self._reference, candidate_evidence, self.contract)
        self.prepare_cells()
        acceptance_groups = tuple(name for name, _values in self._reference.groups)
        previous_cells = {
            (failure.x, failure.y, failure.width, failure.height): failure.failed_groups
            for failure in previous.failures
            if failure.width <= self.cell_size_px and failure.height <= self.cell_size_px
        }
        failures: list[RepairFailure] = []
        for y in range(0, height, self.cell_size_px):
            for x in range(0, width, self.cell_size_px):
                cell_height = min(self.cell_size_px, height - y)
                cell_width = min(self.cell_size_px, width - x)
                bounds = (x, y, cell_width, cell_height)
                if bounds in exact_source_bounds:
                    failed_groups = ()
                elif bounds not in changed_bounds:
                    failed_groups = previous_cells.get(bounds, ())
                else:
                    reference = self._cell_references[
                        (x, y, cell_width, cell_height, acceptance_groups)
                    ]
                    cell = compare_acceptance_groups(
                        reference,
                        compute_acceptance_groups(
                            candidate[y : y + cell_height, x : x + cell_width],
                            self.physical_grid,
                            groups=acceptance_groups,
                        ),
                        self.contract,
                    )
                    failed_groups = cell.failed_groups
                if failed_groups:
                    failures.append(
                        RepairFailure(
                            x,
                            y,
                            cell_width,
                            cell_height,
                            width,
                            height,
                            failed_groups,
                        )
                    )
        if not failures and comparison.failed_groups:
            failures.append(
                RepairFailure(
                    0,
                    0,
                    width,
                    height,
                    width,
                    height,
                    comparison.failed_groups,
                )
            )
        return LocalizedAcceptanceResult(not failures, tuple(failures))
