from __future__ import annotations

from pathlib import Path

import pytest

from denser.container.mcv2 import McV2CorruptionError, McV2Reader, McV2Writer
from denser.core.models import ByteBreakdown, TileAddress


def _write(path: Path) -> Path:
    writer = McV2Writer(path)
    writer.add_tile(TileAddress(0, 0, 0, 8, 8), b"abc", ByteBreakdown(payload=3))
    writer.add_tile(TileAddress(0, 0, 8, 8, 8), b"defg", ByteBreakdown(payload=4))
    writer.finalize()
    return path


def test_mcv2_random_tile_round_trip_and_exact_ledger(tmp_path: Path) -> None:
    path = _write(tmp_path / "fixture.mcv2")
    reader = McV2Reader(path)
    assert reader.read_tile(reader.addresses[1]) == b"defg"
    assert reader.payload_reads == [1]
    assert reader.byte_ledger().complete_bytes == path.stat().st_size


@pytest.mark.parametrize("region", ["header", "packet", "index", "integrity", "truncate"])
def test_mcv2_fails_closed_for_every_structural_region(tmp_path: Path, region: str) -> None:
    path = _write(tmp_path / f"{region}.mcv2")
    reader = McV2Reader(path)
    if region == "truncate":
        with path.open("r+b") as stream:
            stream.truncate(path.stat().st_size - 1)
    else:
        offsets = {
            "header": 0,
            "packet": reader.packet_region_offset,
            "index": reader.index_offset,
            "integrity": reader.integrity_offset,
        }
        with path.open("r+b") as stream:
            stream.seek(offsets[region])
            byte = stream.read(1)
            stream.seek(offsets[region])
            stream.write(bytes([byte[0] ^ 1]))
    if region == "packet":
        corrupted = McV2Reader(path)
        with pytest.raises(McV2CorruptionError):
            corrupted.read_tile(corrupted.addresses[0])
    else:
        with pytest.raises(McV2CorruptionError):
            McV2Reader(path)

