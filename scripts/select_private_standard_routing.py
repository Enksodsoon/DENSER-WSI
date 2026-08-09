from __future__ import annotations

import argparse
import json
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.experiments.standard_routing import derive_development_winner_routes
from denser.governance.run_layout import RunLayout


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive a private project route from full-ladder development winners"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--full-ladder-report", type=Path, required=True)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    report_path = arguments.full_ladder_report.resolve()
    try:
        report_path.relative_to(layout.run_root)
    except ValueError as error:
        raise ValueError("full-ladder report must remain beneath the private run root") from error
    if not report_path.is_file():
        raise ValueError("full-ladder report does not exist")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    routing = derive_development_winner_routes(report)
    output = layout.resolve(
        "manifests", f"generation-{arguments.generation}-standard-routing.private.json"
    )
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(canonical_json_bytes(routing) + b"\n")
    temporary.replace(output)
    print(
        json.dumps(
            {
                "development_tiles": routing["development_tiles"],
                "profiles_by_project": {
                    project: len(profiles)
                    for project, profiles in routing["routes"].items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
