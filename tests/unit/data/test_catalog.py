from __future__ import annotations

import pytest

from denser.data.catalog import CatalogAdmission, admit_conformance_fixture


def test_admits_checksum_verified_file_only_for_non_primary_conformance() -> None:
    admission = admit_conformance_fixture(
        catalog_id="WSI-TEST",
        url_type="file",
        resolved_sha256="a" * 64,
        resolved_bytes=1234,
        requested_role="non_primary_conformance",
    )

    assert admission == CatalogAdmission(
        catalog_id="WSI-TEST",
        role="non_primary_conformance",
        resolved_sha256="a" * 64,
        resolved_bytes=1234,
        primary_experiment_eligible=False,
    )


@pytest.mark.parametrize("checksum", [None, "", "abc", "g" * 64])
def test_rejects_missing_or_invalid_resolved_checksum(checksum: str | None) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        admit_conformance_fixture(
            catalog_id="WSI-TEST",
            url_type="file",
            resolved_sha256=checksum,
            resolved_bytes=1234,
            requested_role="non_primary_conformance",
        )


def test_rejects_directory_and_primary_experiment_admission() -> None:
    with pytest.raises(ValueError, match="file URL"):
        admit_conformance_fixture(
            catalog_id="WSI-DIRECTORY",
            url_type="directory",
            resolved_sha256="a" * 64,
            resolved_bytes=1234,
            requested_role="non_primary_conformance",
        )

    with pytest.raises(ValueError, match="non-primary"):
        admit_conformance_fixture(
            catalog_id="WSI-PRIMARY",
            url_type="file",
            resolved_sha256="a" * 64,
            resolved_bytes=1234,
            requested_role="primary_experiment",
        )
