from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from denser.governance.public_release import PublicReleasePolicy, check_public_release


def test_clean_source_tree_is_public_safe(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/module.py").write_text("VALUE = 1\n", encoding="utf-8")
    report = check_public_release(tmp_path, PublicReleasePolicy())
    assert report.passed
    assert report.findings == ()


@pytest.mark.parametrize("name", ["slide.svs", "result.mcv2"])
def test_wsi_payload_is_rejected_by_extension(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_bytes(b"payload")
    report = check_public_release(tmp_path, PublicReleasePolicy())
    assert [(item.code, item.path) for item in report.findings] == [
        ("forbidden_extension", name)
    ]


def test_user_profile_absolute_path_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "report.txt").write_text(
        "source=C:\\Users\\researcher\\private\\slide.svs\n", encoding="utf-8"
    )
    report = check_public_release(tmp_path, PublicReleasePolicy())
    assert "absolute_local_path" in report.error_codes


def test_signed_download_url_is_rejected(tmp_path: Path) -> None:
    signature_parameter = "X-Amz-" + "Signature"
    (tmp_path / "report.txt").write_text(
        f"https://example.invalid/file?{signature_parameter}=secret\n", encoding="utf-8"
    )
    report = check_public_release(tmp_path, PublicReleasePolicy())
    assert "signed_url" in report.error_codes


def test_public_report_rejects_source_fields_and_small_cells(tmp_path: Path) -> None:
    reports = tmp_path / "reports/public"
    reports.mkdir(parents=True)
    (reports / "summary.json").write_text(
        json.dumps({"case_id": "hidden", "groups": [{"count": 4}]}) + "\n",
        encoding="utf-8",
    )
    report = check_public_release(tmp_path, PublicReleasePolicy())
    assert {"forbidden_report_field", "small_aggregate_cell"}.issubset(report.error_codes)


def test_scanner_ignores_git_and_virtual_environment_internals(tmp_path: Path) -> None:
    (tmp_path / ".git/objects").mkdir(parents=True)
    (tmp_path / ".venv/cache").mkdir(parents=True)
    (tmp_path / ".git/objects/private.svs").write_bytes(b"ignored")
    (tmp_path / ".venv/cache/private.svs").write_bytes(b"ignored")
    assert check_public_release(tmp_path, PublicReleasePolicy()).passed


def test_public_release_cli_runs_from_source_checkout() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "scripts/check_public_release.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "PASS public release scan" in result.stdout
