from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.experiments.standard_routing import evaluate_development_route_fairness
from denser.governance.run_layout import RunLayout


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate private development route fairness")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--full-ladder-report", type=Path, required=True)
    parser.add_argument("--routed-report", type=Path, required=True)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    full_path = arguments.full_ladder_report.resolve()
    routed_path = arguments.routed_report.resolve()
    for path in (full_path, routed_path):
        if not path.is_relative_to(layout.run_root) or not path.is_file():
            raise ValueError("fairness inputs must be private run files")
    full_bytes = full_path.read_bytes()
    routed_bytes = routed_path.read_bytes()
    routed = json.loads(routed_bytes)
    evidence = evaluate_development_route_fairness(json.loads(full_bytes), routed)
    evidence.update(
        {
            "generation": arguments.generation,
            "code_commit": routed.get("code_commit"),
            "image_digest": routed.get("image_digest"),
            "routing_digest": routed.get("standard_routing_digest"),
            "full_report_sha256": hashlib.sha256(full_bytes).hexdigest(),
            "routed_report_sha256": hashlib.sha256(routed_bytes).hexdigest(),
        }
    )
    output = layout.resolve(
        "results",
        "development",
        f"generation-{arguments.generation}",
        f"standard-routing-fairness-{str(evidence['routing_digest'])[:12]}.private.json",
    )
    output.write_bytes(canonical_json_bytes(evidence) + b"\n")
    print(
        json.dumps(
            {
                "development_tiles": evidence["development_tiles"],
                "exact_fraction": evidence["exact_fraction"],
                "maximum_complete_byte_ratio": evidence["maximum_complete_byte_ratio"],
                "median_complete_byte_ratio": evidence["median_complete_byte_ratio"],
                "passed": evidence["passed"],
                "failure_codes": evidence["failure_codes"],
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
