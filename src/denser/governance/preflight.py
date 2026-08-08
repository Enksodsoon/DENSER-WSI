from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from denser.governance.public_release import (
    PublicReleaseFinding,
    PublicReleasePolicy,
    check_public_release,
)
from denser.governance.redaction import redact_source_identifier


@dataclass(frozen=True)
class PreflightReport:
    findings: tuple[PublicReleaseFinding, ...]
    scanned_files: int

    @property
    def passed(self) -> bool:
        return not self.findings

    @property
    def error_codes(self) -> frozenset[str]:
        return frozenset(item.code for item in self.findings)


def run_preflight(root: Path) -> PreflightReport:
    release = check_public_release(root, PublicReleasePolicy())
    return PreflightReport(release.findings, release.scanned_files)


__all__ = ["PreflightReport", "redact_source_identifier", "run_preflight"]
