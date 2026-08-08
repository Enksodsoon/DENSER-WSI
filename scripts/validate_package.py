from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

from jsonschema import Draft202012Validator


EXPECTED_PLAN_HASH = "94c3d8b7833883186a293c904d7ccb6f782113b78cc5750f570ca4d7a90dc0fd"
EXPECTED_SOURCE_COMMIT = "ad6e2b6286df4cd39bd7249f66a73dbc7ffae7bc"
FORBIDDEN_EXTENSIONS = {
    ".svs", ".vsi", ".ndpi", ".mrxs", ".scn", ".bif", ".czi",
    ".mcv1", ".parquet", ".tif", ".tiff",
}
REQUIRED_FILES = {
    "AGENTS.md",
    "AUTONOMOUS_EXECUTION.md",
    "CODEX_START_HERE.md",
    "LICENSE",
    "PUBLIC_RELEASE_POLICY.md",
    "RECONSTRUCTION_PROVENANCE.md",
    "SECURITY.md",
    "docs/audits/2026-08-07-denser-wsi-full-plan-audit.md",
    "docs/provenance/DENSER-WSI-Complete-Final-Plan.md",
    "docs/superpowers/specs/2026-08-07-denser-wsi-falsification-design.md",
    "docs/superpowers/plans/2026-08-07-denser-wsi-pilot-implementation-plan.md",
    "docs/plans/active/current.md",
}
SCHEMA_BINDINGS = {
    "configs/governance/reconstruction.json": "schemas/reconstruction_provenance.schema.json",
    "configs/governance/public_release.json": "schemas/public_release.schema.json",
    "configs/execution/run_layout.json": "schemas/run_layout.schema.json",
    "configs/execution/autonomous.json": "schemas/autonomous_execution.schema.json",
    "configs/experiment/study.json": "schemas/study.schema.json",
    "configs/experiment/he_v1_controls.json": "schemas/he_v1_controls.schema.json",
}


@dataclass(frozen=True)
class ValidationReport:
    checks: dict[str, bool]

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(name for name, passed in self.checks.items() if not passed)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def _json(root: Path, relative: str) -> dict[str, object]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _safe(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _schema_validation(root: Path) -> bool:
    for document_path, schema_path in SCHEMA_BINDINGS.items():
        document = _json(root, document_path)
        schema = _json(root, schema_path)
        if list(Draft202012Validator(schema).iter_errors(document)):
            return False
    return True


def _sensitive_payload_scan(root: Path) -> bool:
    excluded_parts = {".git", ".venv", ".pytest_cache", "__pycache__"}
    for path in root.rglob("*"):
        if not path.is_file() or excluded_parts.intersection(path.parts):
            continue
        if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            return False
    return True


def validate_package(root: Path) -> ValidationReport:
    root = root.resolve()

    def plan_hash() -> bool:
        data = (root / "docs/provenance/DENSER-WSI-Complete-Final-Plan.md").read_bytes()
        return hashlib.sha256(data).hexdigest() == EXPECTED_PLAN_HASH

    def truthful_provenance() -> bool:
        value = _json(root, "configs/governance/reconstruction.json")
        return (
            value["referenced_source_commit"] == EXPECTED_SOURCE_COMMIT
            and value["source_artifact_available"] is False
            and value["source_commit_checked_out"] is False
        )

    def task_count() -> bool:
        text = (root / "docs/superpowers/plans/2026-08-07-denser-wsi-pilot-implementation-plan.md").read_text(encoding="utf-8")
        tasks = [int(value) for value in re.findall(r"^### Task (\d+):", text, flags=re.MULTILINE)]
        return tasks == list(range(1, 30))

    def phase_order() -> bool:
        phases = _json(root, "configs/execution/autonomous.json")["phases"]
        return phases.index("orchestration") < phases.index("synthetic") < phases.index("development") < phases.index("pilot")

    def automatic_freeze() -> bool:
        study = _json(root, "configs/experiment/study.json")
        phases = _json(root, "configs/execution/autonomous.json")["phases"]
        return study["automatic_freeze"] is True and phases.index("freeze") < phases.index("final_holdout")

    def fair_comparator() -> bool:
        study = _json(root, "configs/experiment/study.json")
        return (
            study["standard_uses_shared_he_v1"] is True
            and study["standard_uses_shared_lossless_fallback"] is True
            and study["minimum_standard_codec_families"] >= 2
        )

    def public_private_boundary() -> bool:
        layout = _json(root, "configs/execution/run_layout.json")
        run_root = PureWindowsPath(layout["run_root"])
        return bool(run_root.drive) and run_root.is_absolute() and run_root.drive.upper() == "D:"

    def public_policy() -> bool:
        policy = _json(root, "configs/governance/public_release.json")
        extensions = set(policy["forbidden_extensions"])
        return (
            policy["model"] == "code_and_aggregates"
            and policy["minimum_aggregate_cell_count"] >= 5
            and FORBIDDEN_EXTENSIONS.issubset(extensions)
            and policy["github_actions_real_data_artifacts"] is False
        )

    def claim_boundaries() -> bool:
        claims = _json(root, "configs/experiment/study.json")["claims"]
        return bool(claims) and all(value is False for value in claims.values())

    study = lambda: _json(root, "configs/experiment/study.json")
    checks = {
        "plan_hash": _safe(plan_hash),
        "truthful_provenance": _safe(truthful_provenance),
        "task_count": _safe(task_count),
        "phase_order": _safe(phase_order),
        "automatic_freeze": _safe(automatic_freeze),
        "full_slide_final": _safe(lambda: study()["final_full_grid"] is True),
        "no_sample_extrapolation": _safe(lambda: study()["sampled_tile_extrapolation"] is False),
        "fair_comparator": _safe(fair_comparator),
        "case_disjointness": _safe(lambda: study()["partition_unit"] == "case_group_sha256"),
        "physical_scale": _safe(lambda: study()["primary_mpp_um"] == [0.2, 0.3] and study()["evidence_cell_um"] == 8.0),
        "certificate_semantics": _safe(lambda: study()["primary_certificate_mode"] == "self_verifying"),
        "public_private_boundary": _safe(public_private_boundary),
        "public_policy": _safe(public_policy),
        "claim_boundaries": _safe(claim_boundaries),
        "schema_validation": _safe(lambda: _schema_validation(root)),
        "required_files": _safe(lambda: all((root / path).is_file() for path in REQUIRED_FILES)),
        "sensitive_payload_scan": _safe(lambda: _sensitive_payload_scan(root)),
    }
    return ValidationReport(checks=checks)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = validate_package(root)
    for name, passed in report.checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"{sum(report.checks.values())}/{len(report.checks)} checks passed")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
