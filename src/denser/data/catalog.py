from __future__ import annotations

import re
from dataclasses import dataclass


_SHA256 = re.compile(r"[0-9a-f]{64}")
_CONFORMANCE_ROLE = "non_primary_conformance"


@dataclass(frozen=True, slots=True)
class CatalogAdmission:
    """A checksum-resolved catalog file admitted outside scientific cohorts."""

    catalog_id: str
    role: str
    resolved_sha256: str
    resolved_bytes: int
    primary_experiment_eligible: bool = False


def admit_conformance_fixture(
    *,
    catalog_id: str,
    url_type: str,
    resolved_sha256: str | None,
    resolved_bytes: int,
    requested_role: str,
) -> CatalogAdmission:
    """Validate a catalog item for reader/conformance use only.

    The catalog is discovery metadata, not an experimental manifest. A caller
    must independently resolve the exact checksum and size from an
    authoritative source before admission.
    """

    if url_type.casefold() != "file":
        raise ValueError("catalog admission requires a direct file URL")
    if requested_role != _CONFORMANCE_ROLE:
        raise ValueError("catalog fixtures are restricted to non-primary conformance")
    if resolved_sha256 is None or _SHA256.fullmatch(resolved_sha256.casefold()) is None:
        raise ValueError("a resolved 64-character SHA-256 is required")
    if resolved_bytes <= 0:
        raise ValueError("resolved byte count must be positive")
    if not catalog_id.strip():
        raise ValueError("catalog ID cannot be empty")

    return CatalogAdmission(
        catalog_id=catalog_id,
        role=_CONFORMANCE_ROLE,
        resolved_sha256=resolved_sha256.casefold(),
        resolved_bytes=resolved_bytes,
        primary_experiment_eligible=False,
    )
