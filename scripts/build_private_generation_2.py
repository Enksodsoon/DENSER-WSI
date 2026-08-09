from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.data.gdc import GdcClient, query_open_he_slides
from denser.data.generation import select_scale_verified_generation
from denser.governance.run_layout import RunLayout
from denser.wsi.remote_metadata import probe_remote_tiff_mpp


PRIMARY_PROJECTS = (
    "TCGA-BRCA",
    "TCGA-KIRC",
    "TCGA-LUAD",
    "TCGA-COAD",
    "TCGA-HNSC",
    "TCGA-LIHC",
)


def _load_or_create_salt(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_bytes()
    else:
        value = secrets.token_bytes(32)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    if len(value) != 32:
        raise ValueError("private generation salt is invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a scale-prefiltered, case-disjoint private Generation 2 cohort"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260809)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    layout.ensure()
    output = layout.resolve("manifests", "generation-2-selected-sources.private.json")
    audit_output = layout.resolve(
        "results", "generation-2", "selection-audit.private.json"
    )
    if output.exists() or audit_output.exists():
        raise FileExistsError("Generation 2 cohort already exists and cannot be overwritten")
    prior_cases: set[str] = set()
    prior_files: set[str] = set()
    for manifest_path in layout.resolve("manifests").glob("*selected-sources.private.json"):
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        for row in document.get("rows", []):
            if isinstance(row, dict):
                if isinstance(row.get("case_id"), str):
                    prior_cases.add(row["case_id"])
                if isinstance(row.get("file_uuid"), str):
                    prior_files.add(row["file_uuid"])
    records = query_open_he_slides(GdcClient(), PRIMARY_PROJECTS)
    selection = select_scale_verified_generation(
        records,
        projects=PRIMARY_PROJECTS,
        excluded_case_ids=prior_cases,
        excluded_file_uuids=prior_files,
        salt=_load_or_create_salt(
            layout.resolve("secrets", "generation-2-cohort-salt.bin")
        ),
        seed=arguments.seed,
        probe=probe_remote_tiff_mpp,
    )
    output.write_bytes(canonical_json_bytes(selection.manifest) + b"\n")
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    audit_output.write_bytes(canonical_json_bytes(selection.audit) + b"\n")
    counts = selection.audit["partition_counts"]
    print(
        json.dumps(
            {
                "generation": 2,
                "queried_open_slides": len(records),
                "selected": selection.audit["selected_count"],
                "partition_counts": counts,
                "compression_outcomes_inspected": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
