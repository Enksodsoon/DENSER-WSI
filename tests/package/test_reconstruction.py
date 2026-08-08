from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.validate_package import validate_package


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def package_copy(tmp_path: Path) -> Path:
    for name in ("configs", "docs", "schemas"):
        shutil.copytree(ROOT / name, tmp_path / name)
    for name in (
        "AGENTS.md",
        "AUTONOMOUS_EXECUTION.md",
        "CODEX_START_HERE.md",
        "LICENSE",
        "PUBLIC_RELEASE_POLICY.md",
        "RECONSTRUCTION_PROVENANCE.md",
        "pyproject.toml",
    ):
        shutil.copy2(ROOT / name, tmp_path / name)
    return tmp_path


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_error(root: Path, code: str) -> None:
    report = validate_package(root)
    assert code in report.errors


def test_complete_reconstruction_passes_all_seventeen_checks() -> None:
    report = validate_package(ROOT)
    assert report.passed
    assert len(report.checks) == 17
    assert set(report.checks.values()) == {True}


def test_plan_tampering_breaks_authenticated_hash(package_copy: Path) -> None:
    path = package_copy / "docs/provenance/DENSER-WSI-Complete-Final-Plan.md"
    path.write_text(path.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    assert_error(package_copy, "plan_hash")


def test_provenance_cannot_claim_unavailable_commit_checkout(package_copy: Path) -> None:
    path = package_copy / "configs/governance/reconstruction.json"
    data = load_json(path)
    data["source_commit_checked_out"] = True
    write_json(path, data)
    assert_error(package_copy, "truthful_provenance")


def test_plan_must_retain_all_twenty_nine_tasks(package_copy: Path) -> None:
    path = package_copy / "docs/superpowers/plans/2026-08-07-denser-wsi-pilot-implementation-plan.md"
    path.write_text(path.read_text(encoding="utf-8").replace("### Task 29:", "### Removed 29:"), encoding="utf-8")
    assert_error(package_copy, "task_count")


def test_orchestrator_precedes_real_experiments(package_copy: Path) -> None:
    path = package_copy / "configs/execution/autonomous.json"
    data = load_json(path)
    phases = data["phases"]
    assert isinstance(phases, list)
    phases.remove("orchestration")
    phases.append("orchestration")
    write_json(path, data)
    assert_error(package_copy, "phase_order")


def test_final_freeze_is_automatic_and_mandatory(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["automatic_freeze"] = False
    write_json(path, data)
    assert_error(package_copy, "automatic_freeze")


def test_final_endpoint_requires_every_level_zero_tile(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["final_full_grid"] = False
    write_json(path, data)
    assert_error(package_copy, "full_slide_final")


def test_primary_endpoint_forbids_sample_extrapolation(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["sampled_tile_extrapolation"] = True
    write_json(path, data)
    assert_error(package_copy, "no_sample_extrapolation")


def test_standard_comparator_uses_shared_contract_and_fallback(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["standard_uses_shared_he_v1"] = False
    write_json(path, data)
    assert_error(package_copy, "fair_comparator")


def test_partitions_are_case_group_disjoint(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["partition_unit"] = "file"
    write_json(path, data)
    assert_error(package_copy, "case_disjointness")


def test_primary_physical_scale_band_is_locked(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["primary_mpp_um"] = [0.1, 1.0]
    write_json(path, data)
    assert_error(package_copy, "physical_scale")


def test_primary_certificate_is_self_verifying(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["primary_certificate_mode"] = "attested_digest"
    write_json(path, data)
    assert_error(package_copy, "certificate_semantics")


def test_private_run_root_must_be_external_to_repository(package_copy: Path) -> None:
    path = package_copy / "configs/execution/run_layout.json"
    data = load_json(path)
    data["run_root"] = ".runtime"
    write_json(path, data)
    assert_error(package_copy, "public_private_boundary")


def test_public_policy_blocks_wsi_and_detailed_results(package_copy: Path) -> None:
    path = package_copy / "configs/governance/public_release.json"
    data = load_json(path)
    data["forbidden_extensions"] = [".tmp"]
    write_json(path, data)
    assert_error(package_copy, "public_policy")


def test_clinical_and_novelty_claims_remain_prohibited(package_copy: Path) -> None:
    path = package_copy / "configs/experiment/study.json"
    data = load_json(path)
    data["claims"]["clinical_noninferiority"] = True
    write_json(path, data)
    assert_error(package_copy, "claim_boundaries")


def test_all_json_documents_validate_against_their_schemas(package_copy: Path) -> None:
    path = package_copy / "configs/execution/run_layout.json"
    data = load_json(path)
    del data["run_root"]
    write_json(path, data)
    assert_error(package_copy, "schema_validation")


def test_required_operator_documents_are_present(package_copy: Path) -> None:
    (package_copy / "AUTONOMOUS_EXECUTION.md").unlink()
    assert_error(package_copy, "required_files")


def test_package_tree_contains_no_sensitive_payload(package_copy: Path) -> None:
    (package_copy / "private-slide.svs").write_bytes(b"not allowed")
    assert_error(package_copy, "sensitive_payload_scan")
