from __future__ import annotations

from pathlib import Path
from dataclasses import asdict

import typer

from denser.governance.preflight import run_preflight
from denser.core.canonical import canonical_json_bytes
from denser.toolchain.probe import probe_toolchain
from denser.toolchain.sbom import write_sbom


app = typer.Typer(
    name="denser",
    help="DENSER-WSI falsification-first research tooling.",
    no_args_is_help=True,
)


@app.callback()
def root_command() -> None:
    """DENSER-WSI command group."""


@app.command("preflight")
def preflight_command(
    root: Path = typer.Option(Path("."), "--root", exists=True, file_okay=False),
) -> None:
    report = run_preflight(root)
    for finding in report.findings:
        typer.echo(f"FAIL {finding.code}: {finding.path}")
    if not report.passed:
        raise typer.Exit(code=1)
    typer.echo(f"PASS preflight: {report.scanned_files} files")


@app.command("toolchain-report")
def toolchain_report_command(
    output: Path = typer.Option(..., "--output", dir_okay=False),
    sbom_output: Path = typer.Option(
        Path("reports/toolchain.spdx.json"), "--sbom-output", dir_okay=False
    ),
    container_digest: str | None = typer.Option(None, "--container-digest"),
) -> None:
    report = probe_toolchain(container_digest=container_digest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(asdict(report)) + b"\n")
    sbom_digest = write_sbom(report, sbom_output)
    available = sum(record.available for record in report.tools)
    typer.echo(
        f"PASS toolchain: {available}/{len(report.tools)} available; "
        f"SBOM sha256={sbom_digest}"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
