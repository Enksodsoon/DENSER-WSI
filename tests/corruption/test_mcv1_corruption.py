from __future__ import annotations

from pathlib import Path

import pytest

from denser.container.mcv1 import McV1CorruptionError, McV1Reader, McV1Writer
from denser.core.models import ByteBreakdown, TileAddress


ADDRESS = TileAddress(0, 0, 0, 2, 2)


def _container(path: Path) -> Path:
    writer = McV1Writer(path)
    writer.add_tile(
        ADDRESS,
        b"payload-certificate",
        ByteBreakdown(payload=7, certificate=12),
    )
    writer.finalize()
    return path


def _flip(path: Path, offset: int) -> None:
    data = bytearray(path.read_bytes())
    data[offset] ^= 0x80
    path.write_bytes(data)


def test_payload_or_certificate_corruption_fails_before_return(tmp_path: Path) -> None:
    path = _container(tmp_path / "payload.mcv1")
    reader = McV1Reader(path)
    _flip(path, reader.packet_region_offset + 9)
    with pytest.raises(McV1CorruptionError, match="packet digest"):
        McV1Reader(path).read_tile(ADDRESS)


def test_index_corruption_fails_closed(tmp_path: Path) -> None:
    path = _container(tmp_path / "index.mcv1")
    reader = McV1Reader(path)
    _flip(path, reader.index_offset)
    with pytest.raises(McV1CorruptionError, match="index digest"):
        McV1Reader(path)


def test_header_length_corruption_fails_closed(tmp_path: Path) -> None:
    path = _container(tmp_path / "header.mcv1")
    _flip(path, 24)
    with pytest.raises(McV1CorruptionError, match="header"):
        McV1Reader(path)


@pytest.mark.parametrize("remove_bytes", [1, 31, 64, 128])
def test_truncation_at_structural_boundaries_fails_closed(
    tmp_path: Path, remove_bytes: int
) -> None:
    path = _container(tmp_path / f"truncated-{remove_bytes}.mcv1")
    data = path.read_bytes()
    path.write_bytes(data[:-remove_bytes])
    with pytest.raises(McV1CorruptionError):
        McV1Reader(path)
