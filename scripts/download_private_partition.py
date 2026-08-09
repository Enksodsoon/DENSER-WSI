from __future__ import annotations

import argparse
import json
from pathlib import Path

from denser.data.private_cohort import download_manifest_partition
from denser.governance.run_layout import PrivateRunLock, RunLayout


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded verified private-cohort downloader")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--partition", choices=("development", "pilot", "tuning", "final"), required=True)
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--max-concurrent-files", type=int, choices=(1, 2), default=2)
    parser.add_argument("--generation", type=int, default=1)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    with PrivateRunLock(layout, "download"):
        records = download_manifest_partition(
            arguments.manifest,
            layout,
            arguments.partition,
            max_files=arguments.max_files,
            max_concurrent_files=arguments.max_concurrent_files,
            generation=arguments.generation,
        )
    # Intentionally emit counts and sizes only: identifiers and paths stay private.
    print(json.dumps({"downloaded_or_verified": len(records), "verified_bytes": sum(row.byte_count for row in records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
