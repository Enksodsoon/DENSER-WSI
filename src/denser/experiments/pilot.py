from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.core.errors import PartitionViolation
from denser.data.manifest import PartitionManifest


@dataclass(frozen=True, slots=True)
class PilotObservation:
    method: str
    complete_bytes: int
    repair_fraction: float
    fallback_fraction: float
    dns: float | None


@dataclass(frozen=True, slots=True)
class PilotConfig:
    output_root: Path
    observations: tuple[PilotObservation, ...] = ()
    max_repair_fraction: float = 0.10
    max_fallback_fraction: float = 0.10


@dataclass(frozen=True, slots=True)
class PilotReport:
    rate_scope: str
    whole_slide_reduction: None
    classification: str
    complete_sampled_bytes: dict[str, int]
    repair_fraction: float | None
    fallback_fraction: float | None
    dns_median: float | None
    calibration_digest: str
    slide_count: int


def run_pilot(
    config: PilotConfig, manifest: PartitionManifest, calibration_digest: str
) -> PilotReport:
    if not manifest.rows or any(row.partition != "pilot" for row in manifest.rows):
        raise PartitionViolation("pilot run accepts pilot rows only")
    if len(calibration_digest) != 64:
        raise ValueError("pilot requires a calibration SHA-256 digest")
    totals: dict[str, int] = {}
    for row in config.observations:
        totals[row.method] = totals.get(row.method, 0) + row.complete_bytes
    denser = [row for row in config.observations if row.method == "denser"]
    repair = statistics.mean(row.repair_fraction for row in denser) if denser else None
    fallback = statistics.mean(row.fallback_fraction for row in denser) if denser else None
    dns_values = [row.dns for row in denser if row.dns is not None]
    dns_median = statistics.median(dns_values) if dns_values else None
    if not {"standard", "uniform", "denser"}.issubset(totals):
        classification = "not_evaluable"
    else:
        classification = "met" if (
            totals["denser"] < totals["uniform"]
            and repair is not None and repair <= config.max_repair_fraction
            and fallback is not None and fallback <= config.max_fallback_fraction
        ) else "not_met"
    report = PilotReport(
        "sampled_tiles_only",
        None,
        classification,
        totals,
        repair,
        fallback,
        dns_median,
        calibration_digest,
        len(manifest.rows),
    )
    output = Path(config.output_root) / "pilot-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(asdict(report)) + b"\n")
    return report
