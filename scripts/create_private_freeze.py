from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import jsonschema

from denser.experiments.freeze import create_freeze_record, write_freeze_record
from denser.experiments.runtime_freeze import build_runtime_freeze_context
from denser.governance.run_layout import RunLayout


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the automatic immutable private final freeze")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--image-digest", required=True)
    arguments = parser.parse_args()
    repo = arguments.repo_root.resolve(strict=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    context = build_runtime_freeze_context(
        repo,
        arguments.run_root,
        generation=arguments.generation,
        git_commit=commit,
        dirty_tree=dirty,
        container_image_digest=arguments.image_digest,
    )
    record = create_freeze_record(context)
    schema = json.loads(
        (repo / "schemas" / "freeze_record.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(asdict(record))
    layout = RunLayout(repo, arguments.run_root)
    output = layout.resolve(
        "results", "final", f"generation-{arguments.generation}", "freeze-record.json"
    )
    if output.exists():
        raise FileExistsError("final freeze already exists and cannot be overwritten")
    write_freeze_record(output, record)
    print(
        json.dumps(
            {
                "generation": arguments.generation,
                "freeze_digest": record.freeze_digest,
                "git_commit": record.git_commit,
                "expected_final_slides": record.expected_final_slide_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
