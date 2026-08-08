from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from denser.cli import app
from denser.toolchain.probe import ToolRecord, ToolchainReport, parse_version
from denser.toolchain.sbom import write_sbom


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cjxl v0.12.0", (0, 12, 0)),
        ("OpenJPEG version 2.5.4", (2, 5, 4)),
        ("libvips 8.18.4", (8, 18, 4)),
        ("Python 3.12.13", (3, 12, 13)),
    ],
)
def test_parse_native_version(text: str, expected: tuple[int, int, int]) -> None:
    assert parse_version(text) == expected


def test_parse_native_version_rejects_unversioned_output() -> None:
    with pytest.raises(ValueError, match="semantic version"):
        parse_version("unknown tool")


def test_write_sbom_emits_spdx_packages_and_returns_digest(tmp_path: Path) -> None:
    report = ToolchainReport(
        tools=(
            ToolRecord(
                name="cjxl",
                available=True,
                path="/usr/local/bin/cjxl",
                version=(0, 12, 0),
                executable_sha256="a" * 64,
                build_flags=("JPEGXL_ENABLE_TOOLS=ON",),
                error_code=None,
            ),
        )
    )
    output = tmp_path / "sbom.spdx.json"
    digest = write_sbom(report, output)
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["spdxVersion"] == "SPDX-2.3"
    assert document["packages"][0]["name"] == "cjxl"
    assert document["packages"][0]["versionInfo"] == "0.12.0"
    assert len(digest) == 64


def test_toolchain_report_command_writes_report_and_sbom(tmp_path: Path) -> None:
    report_path = tmp_path / "toolchain.json"
    sbom_path = tmp_path / "toolchain.spdx.json"
    result = CliRunner().invoke(
        app,
        [
            "toolchain-report",
            "--output",
            str(report_path),
            "--sbom-output",
            str(sbom_path),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["tools"]
    assert all("build_flags" in tool for tool in report["tools"])
    assert json.loads(sbom_path.read_text(encoding="utf-8"))["spdxVersion"] == "SPDX-2.3"
