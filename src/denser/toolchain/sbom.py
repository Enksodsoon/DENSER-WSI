from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.core.hashes import sha256_bytes
from denser.toolchain.probe import ToolchainReport


def _created_time() -> str:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_sbom(report: ToolchainReport, output: Path) -> str:
    packages = []
    for record in sorted(report.tools, key=lambda item: item.name):
        if not record.available or record.version is None or record.executable_sha256 is None:
            continue
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-{record.name}",
                "name": record.name,
                "versionInfo": ".".join(str(part) for part in record.version),
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": record.executable_sha256}
                ],
            }
        )
    package_digest = sha256_bytes(canonical_json_bytes(packages))
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "DENSER-WSI native toolchain",
        "documentNamespace": f"https://github.com/Enksodsoon/DENSER-WSI/sbom/{package_digest}",
        "creationInfo": {
            "created": _created_time(),
            "creators": ["Tool: denser-wsi-0.3.0"],
        },
        "packages": packages,
    }
    data = canonical_json_bytes(document) + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return sha256_bytes(data)
