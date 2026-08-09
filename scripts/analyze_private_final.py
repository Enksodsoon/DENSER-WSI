from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from denser.analysis.private_final import analyze_private_final_documents
from denser.core.canonical import canonical_json_bytes
from denser.governance.run_layout import RunLayout


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze frozen private full-slide results")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--seed", type=int, default=20260808)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    result_root = layout.resolve("results", "final", f"generation-{arguments.generation}")
    summary = json.loads(
        (result_root / "execution-summary.private.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        layout.resolve(
            "manifests", f"generation-{arguments.generation}-selected-sources.private.json"
        ).read_text(encoding="utf-8")
    )
    routing = json.loads(
        layout.resolve(
            "manifests", f"generation-{arguments.generation}-standard-routing.private.json"
        ).read_text(encoding="utf-8")
    )
    analyzed = analyze_private_final_documents(
        summary,
        manifest,
        routing,
        seed=arguments.seed,
    )
    document = {
        "version": "DENSER-private-final-analysis-1",
        "generation": arguments.generation,
        "freeze_digest": summary["freeze_digest"],
        "source_data_processed": summary["source_data_processed"],
        "statistical_result": asdict(analyzed.analysis.statistical_result),
        "completeness": asdict(analyzed.analysis.completeness),
        "scientific_outcome": analyzed.analysis.scientific_outcome,
        "performance": summary["performance"],
        "slide_results": [
            {
                **asdict(row),
                "complete_byte_reduction": (
                    1.0 - row.denser_complete_bytes / row.standard_complete_bytes
                ),
            }
            for row in analyzed.rows
        ],
    }
    destination = result_root / "analysis.private.json"
    destination.write_bytes(canonical_json_bytes(document) + b"\n")
    print(
        json.dumps(
            {
                "slide_count": len(analyzed.rows),
                "scientific_outcome": analyzed.analysis.scientific_outcome,
                "median_reduction": analyzed.analysis.statistical_result.median_reduction,
                "lower_bound": analyzed.analysis.statistical_result.lower_bound,
                "encoding_time_ratio": analyzed.analysis.completeness.encoding_time_ratio,
                "cold_decode_p95_ratio": analyzed.analysis.completeness.cold_decode_p95_ratio,
                "warm_decode_p95_ratio": analyzed.analysis.completeness.warm_decode_p95_ratio,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
