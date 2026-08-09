from __future__ import annotations

import argparse
import json
from pathlib import Path

from denser.governance.run_layout import RunLayout
from denser.toolchain.probe import probe_toolchain
from denser.toolchain.sbom import write_sbom


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the pinned private runtime SBOM")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--image-digest", required=True)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    report = probe_toolchain(container_digest=arguments.image_digest)
    unavailable = [record.name for record in report.tools if not record.available]
    if unavailable:
        raise RuntimeError(f"pinned toolchain probe failed for {len(unavailable)} tools")
    output = layout.resolve(
        "results",
        "final",
        f"generation-{arguments.generation}",
        "software-bill-of-materials.spdx.json",
    )
    digest = write_sbom(report, output)
    print(json.dumps({"packages": len(report.tools), "sbom_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
