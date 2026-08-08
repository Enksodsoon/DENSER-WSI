from __future__ import annotations

from pathlib import Path

import typer

from denser.governance.preflight import run_preflight


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
