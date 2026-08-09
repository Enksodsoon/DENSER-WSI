from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.governance.run_layout import RunLayout
from denser.wsi.metadata import MetadataError
from denser.wsi.remote_metadata import probe_remote_tiff_mpp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Header-only private partition physical-scale preflight"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--partition", choices=("development", "pilot", "tuning", "final"), required=True
    )
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    manifest_path = arguments.manifest.resolve(strict=True)
    if not manifest_path.is_relative_to(layout.resolve("manifests")):
        raise ValueError("private source manifest must remain beneath run manifests")
    manifest_bytes = manifest_path.read_bytes()
    document = json.loads(manifest_bytes)
    selected = [
        row
        for row in document.get("rows", [])
        if isinstance(row, dict) and row.get("partition") == arguments.partition
    ]
    selected.sort(key=lambda row: (str(row.get("project_id")), str(row.get("research_id"))))
    rows: list[dict[str, object]] = []
    for slide_index, row in enumerate(selected):
        try:
            metadata = probe_remote_tiff_mpp(str(row["source_url"]))
            eligible = 0.20 <= metadata.mpp <= 0.30
            rows.append(
                {
                    "slide_index": slide_index,
                    "mpp": round(metadata.mpp, 12),
                    "metadata_source": metadata.source,
                    "probe_bytes": metadata.bytes_requested,
                    "eligible": eligible,
                    "reason_code": None if eligible else "physical_scale_outside_primary_band",
                    "outcome_inspected": False,
                }
            )
        except (KeyError, OSError, MetadataError) as error:
            rows.append(
                {
                    "slide_index": slide_index,
                    "mpp": None,
                    "metadata_source": None,
                    "probe_bytes": 0,
                    "eligible": False,
                    "reason_code": "physical_scale_missing_or_access_limited",
                    "error_type": type(error).__name__,
                    "outcome_inspected": False,
                }
            )
    eligible_count = sum(bool(row["eligible"]) for row in rows)
    minimum_required = 18 if arguments.partition == "final" else 6
    report = {
        "version": "DENSER-private-scale-preflight-1",
        "partition": arguments.partition,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "primary_mpp_um": [0.20, 0.30],
        "selected_count": len(selected),
        "eligible_count": eligible_count,
        "phase_classification": (
            "evaluable"
            if eligible_count == len(selected) and eligible_count >= minimum_required
            else "not_evaluable"
        ),
        "compression_outcomes_inspected": False,
        "rows": rows,
    }
    output = layout.resolve(
        "results", arguments.partition, "generation-1", "scale-preflight.private.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(report) + b"\n")
    print(
        json.dumps(
            {
                "partition": arguments.partition,
                "selected": len(selected),
                "eligible": eligible_count,
                "not_eligible_or_unresolved": len(selected) - eligible_count,
                "compression_outcomes_inspected": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
