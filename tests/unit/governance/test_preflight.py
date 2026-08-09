from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from denser.cli import app
from denser.governance.preflight import redact_source_identifier, run_preflight


def test_preflight_rejects_wsi_in_repository(tmp_path: Path) -> None:
    (tmp_path / "patient.svs").write_bytes(b"x")
    report = run_preflight(tmp_path)
    assert "forbidden_extension" in report.error_codes


def test_preflight_accepts_clean_source_tree(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    report = run_preflight(tmp_path)
    assert report.passed
    assert report.scanned_files == 1


def test_redaction_is_deterministic_and_nonreversible() -> None:
    salt = b"0123456789abcdef"
    first = redact_source_identifier("GDC-file-id", salt)
    assert first == redact_source_identifier("GDC-file-id", salt)
    assert "GDC-file-id" not in first
    assert first.startswith("src_")


def test_redaction_changes_with_salt() -> None:
    assert redact_source_identifier("same", b"a" * 16) != redact_source_identifier(
        "same", b"b" * 16
    )


def test_redaction_rejects_short_salt() -> None:
    try:
        redact_source_identifier("value", b"short")
    except ValueError as error:
        assert str(error) == "salt must contain at least 16 bytes"
    else:
        raise AssertionError("short salt was accepted")


def test_preflight_cli_returns_nonzero_for_unsafe_tree(tmp_path: Path) -> None:
    (tmp_path / "patient.svs").write_bytes(b"x")
    result = CliRunner().invoke(app, ["preflight", "--root", str(tmp_path)])
    assert result.exit_code == 1
    assert "forbidden_extension" in result.stdout
