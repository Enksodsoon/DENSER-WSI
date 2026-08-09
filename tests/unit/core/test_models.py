from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from denser.core.models import ByteBreakdown, MethodResult, SlideIdentity, TileAddress


def test_complete_bytes_is_exact_sum() -> None:
    value = ByteBreakdown(
        payload=10,
        repair=2,
        certificate=3,
        reference_evidence=4,
        index=5,
        integrity=6,
        overview=7,
        metadata=8,
        padding=9,
    )
    assert value.complete == 54


def test_byte_breakdown_rejects_negative_category() -> None:
    with pytest.raises(ValueError, match="payload must be non-negative"):
        ByteBreakdown(payload=-1)


def test_tile_address_rejects_negative_coordinates() -> None:
    with pytest.raises(ValueError, match="x must be non-negative"):
        TileAddress(level=0, x=-1, y=0, width=512, height=512)


def test_tile_address_rejects_empty_region() -> None:
    with pytest.raises(ValueError, match="width must be positive"):
        TileAddress(level=0, x=0, y=0, width=0, height=512)


def test_models_are_immutable() -> None:
    address = TileAddress(level=0, x=0, y=0, width=512, height=512)
    with pytest.raises(FrozenInstanceError):
        address.x = 1  # type: ignore[misc]


def test_slide_identity_requires_sha256() -> None:
    with pytest.raises(ValueError, match="source_sha256"):
        SlideIdentity(research_id="R-1", source_sha256="short", case_group_sha256="0" * 64)


def test_method_result_complete_bytes_come_from_breakdown() -> None:
    result = MethodResult(
        method_id="standard",
        profile_id="jpeg-q90",
        status="accepted",
        breakdown=ByteBreakdown(payload=100, certificate=8),
    )
    assert result.complete_bytes == 108
