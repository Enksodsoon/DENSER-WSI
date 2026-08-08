from __future__ import annotations

from dataclasses import asdict, dataclass

from denser.core.canonical import canonical_json_bytes


PARTITIONS = ("development", "pilot", "tuning", "final")


@dataclass(frozen=True, slots=True)
class ManifestCandidate:
    research_id: str
    project_id: str
    case_id: str
    source_sha256: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class PartitionPlan:
    counts: dict[str, int]
    reserve_count: int
    run_salt: bytes

    def __post_init__(self) -> None:
        if tuple(self.counts) != PARTITIONS:
            raise ValueError(f"partition counts must be ordered as {PARTITIONS}")
        if any(count < 0 for count in self.counts.values()) or self.reserve_count < 0:
            raise ValueError("partition and reserve counts cannot be negative")
        if len(self.run_salt) < 16:
            raise ValueError("run salt must contain at least 16 bytes")


@dataclass(frozen=True, slots=True)
class SlideRecord:
    research_id: str
    project_id: str
    case_group_sha256: str
    source_sha256: str
    byte_count: int
    partition: str
    replacement_rank: int | None
    reason_code: str | None = None
    outcome_inspected: bool = False


@dataclass(frozen=True, slots=True)
class PartitionManifest:
    version: str
    seed: int
    rows: tuple[SlideRecord, ...]
    manifest_sha256: str

    def unsigned_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "version": self.version,
                "seed": self.seed,
                "rows": [asdict(row) for row in self.rows],
            }
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "version": self.version,
                "seed": self.seed,
                "rows": [asdict(row) for row in self.rows],
                "manifest_sha256": self.manifest_sha256,
            }
        )
