from __future__ import annotations

from pathlib import Path

import numpy as np

from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import build_default_registry
from denser.container.mcv2 import McV2Writer
from denser.core.models import TileAddress
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.experiments.candidate_selection import select_smallest_accepted_candidate
from denser.adapter.service import get_slide_metadata, get_tile


def audited_fixture_container(tmp_path: Path) -> tuple[Path, np.ndarray, TileAddress]:
    pixels = np.arange(16 * 16 * 3, dtype=np.uint8).reshape(16, 16, 3)
    candidate = SharedLosslessCodec().encode(pixels)
    selected = select_smallest_accepted_candidate(
        pixels,
        [candidate],
        build_default_registry(),
        AcceptanceContract(),
        PhysicalGrid(0.25, 0.25),
        cell_size_px=8,
    )
    address = TileAddress(0, 0, 0, 16, 16)
    path = tmp_path / "audited.mcv2"
    writer = McV2Writer(path)
    writer.add_tile(address, selected.packet, selected.breakdown)
    writer.finalize()
    return path, pixels, address


def test_adapter_returns_verified_random_tile_without_source_wsi(tmp_path: Path) -> None:
    container, expected, address = audited_fixture_container(tmp_path)
    response = get_tile(container, address)
    assert response.verification_passed
    assert response.source_wsi_accessed is False
    np.testing.assert_array_equal(response.rgb, expected)


def test_adapter_metadata_is_container_only_and_complete(tmp_path: Path) -> None:
    container, _expected, address = audited_fixture_container(tmp_path)
    metadata = get_slide_metadata(container)
    assert metadata.format == "MC-V2"
    assert metadata.tile_count == 1
    assert metadata.addresses == (address,)
    assert metadata.complete_bytes == container.stat().st_size
