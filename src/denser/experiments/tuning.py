from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.core.errors import PartitionViolation
from denser.data.manifest import PartitionManifest
from denser.experiments.profile_selection import (
    ProfileResult,
    SelectedProfile,
    SelectionRule,
    select_profile,
)


@dataclass(frozen=True, slots=True)
class TuningConfig:
    output_root: Path
    declared_profile_ids: tuple[str, ...]


def run_tuning(
    config: TuningConfig,
    manifest: PartitionManifest,
    results: tuple[ProfileResult, ...],
) -> SelectedProfile:
    if not manifest.rows or any(row.partition != "tuning" for row in manifest.rows):
        raise PartitionViolation("tuning run accepts tuning rows only")
    if tuple(row.profile_id for row in results) != config.declared_profile_ids:
        raise ValueError("tuning results do not match the predeclared profile grid")
    selected = select_profile(results, SelectionRule())
    output = Path(config.output_root) / "selected-profile.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(asdict(selected)) + b"\n")
    return selected
