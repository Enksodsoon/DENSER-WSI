from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from denser.governance.public_release import PublicReleasePolicy, check_public_release


def main() -> int:
    report = check_public_release(ROOT, PublicReleasePolicy())
    for finding in report.findings:
        detail = f" ({finding.detail})" if finding.detail else ""
        print(f"FAIL {finding.code}: {finding.path}{detail}")
    if report.passed:
        print(f"PASS public release scan: {report.scanned_files} files")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
