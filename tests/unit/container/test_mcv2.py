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


def test_mcv2_resumes_from_fsynced_tile_journal_and_truncates_uncommitted_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "resume.mcv2"
    first = TileAddress(0, 0, 0, 8, 8)
    second = TileAddress(0, 0, 8, 8, 8)
    writer = McV2Writer(path, resume_token="frozen-slide-standard")
    writer.add_tile(first, b"abc", ByteBreakdown(payload=3))
    writer.suspend()
    temporary = path.with_name(f".{path.name}.building")
    with temporary.open("ab") as stream:
        stream.write(b"uncommitted-after-crash")

    resumed = McV2Writer(path, resume_token="frozen-slide-standard")
    assert resumed.checkpointed_addresses == (first,)
    resumed.add_tile(second, b"defg", ByteBreakdown(payload=4))
    resumed.finalize()

    reader = McV2Reader(path)
    assert reader.addresses == (first, second)
    assert reader.read_tile(first) == b"abc"
    assert reader.read_tile(second) == b"defg"


def test_mcv2_resume_rejects_different_freeze_identity(tmp_path: Path) -> None:
    path = tmp_path / "identity.mcv2"
    writer = McV2Writer(path, resume_token="freeze-a")
    writer.add_tile(TileAddress(0, 0, 0, 8, 8), b"abc", ByteBreakdown(payload=3))
    writer.suspend()
    with pytest.raises(McV2CorruptionError, match="resume identity"):
        McV2Writer(path, resume_token="freeze-b")


def test_mcv2_can_roll_back_to_shared_multiwriter_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "rollback.mcv2"
    addresses = (
        TileAddress(0, 0, 0, 8, 8),
        TileAddress(0, 0, 8, 8, 8),
    )
    writer = McV2Writer(path, resume_token="shared")
    for address in addresses:
        writer.add_tile(address, b"abc", ByteBreakdown(payload=3))
        writer.checkpoint()
    writer.rollback_to_checkpoint(1)
    writer.suspend()
    resumed = McV2Writer(path, resume_token="shared")
    assert resumed.checkpointed_addresses == addresses[:1]
    resumed.finalize()
    assert McV2Reader(path).addresses == addresses[:1]


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
