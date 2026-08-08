from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.core.errors import PartitionViolation
from denser.data.manifest import PartitionManifest
from denser.evidence.calibrate import calibrate_contract, verify_calibration
from denser.evidence.controls import CalibrationProfile, ControlPair


@dataclass(frozen=True, slots=True)
class DevelopmentConfig:
    output_root: Path
    candidate_steps: tuple[float, ...] = (1.0, 2.0, 4.0)
    allowed_step_range: tuple[float, float] = (0.5, 8.0)
    mpp_range: tuple[float, float] = (0.10, 1.00)
    control_pairs: tuple[ControlPair, ...] = ()
    measured_source_bytes: int = 0
    measured_peak_scratch_bytes: int = 0


@dataclass(frozen=True, slots=True)
class DevelopmentReport:
    status: str
    slide_count: int
    calibration_digest: str | None
    calibration_audit_status: str | None
    missed_control_ids: tuple[str, ...]
    candidate_steps: tuple[float, ...]
    scratch_multiplier: float | None
    manifest_digest: str
    report_sha256: str


def run_development(
    config: DevelopmentConfig, manifest: PartitionManifest
) -> DevelopmentReport:
    if not manifest.rows or any(row.partition != "development" for row in manifest.rows):
        raise PartitionViolation("development run accepts development rows only")
    low, high = config.allowed_step_range
    if any(step < low or step > high for step in config.candidate_steps):
        raise ValueError("candidate step lies outside the predeclared development range")
    calibration_digest: str | None = None
    calibration_audit_status: str | None = None
    missed_control_ids: tuple[str, ...] = ()
    status = "external_access_limited"
    if config.control_pairs:
        benign = [pair for pair in config.control_pairs if pair.kind == "benign"]
        harmful = [pair for pair in config.control_pairs if pair.kind == "harmful"]
        challenge_ids = tuple(sorted(pair.control_id for pair in harmful))
        calibration = calibrate_contract(
            benign, CalibrationProfile(0.05, challenge_ids)
        )
        audit = verify_calibration(calibration, harmful)
        calibration_audit_status = audit.status
        missed_control_ids = audit.missed_control_ids
        if audit.status == "calibrated":
            calibration_digest = calibration.sha256
            status = "complete"
        else:
            status = "control_audit_failed"
        calibration_path = Path(config.output_root) / "calibration-record.json"
        calibration_path.parent.mkdir(parents=True, exist_ok=True)
        calibration_path.write_bytes(
            canonical_json_bytes(
                {"calibration": asdict(calibration), "harmful_control_audit": asdict(audit)}
            )
            + b"\n"
        )
    scratch = None
    if config.measured_source_bytes > 0:
        scratch = config.measured_peak_scratch_bytes / config.measured_source_bytes
    unsigned = {
        "status": status,
        "slide_count": len(manifest.rows),
        "calibration_digest": calibration_digest,
        "calibration_audit_status": calibration_audit_status,
        "missed_control_ids": list(missed_control_ids),
        "candidate_steps": list(config.candidate_steps),
        "scratch_multiplier": scratch,
        "manifest_digest": manifest.manifest_sha256,
    }
    digest = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    report = DevelopmentReport(
        status,
        len(manifest.rows),
        calibration_digest,
        calibration_audit_status,
        missed_control_ids,
        config.candidate_steps,
        scratch,
        manifest.manifest_sha256,
        digest,
    )
    report_path = Path(config.output_root) / "development-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json_bytes(asdict(report)) + b"\n")
    return report
