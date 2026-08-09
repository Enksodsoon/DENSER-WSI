from __future__ import annotations

from pathlib import Path

from denser.container.mcv1 import McV1Reader, McV1Writer
from denser.core.models import ByteBreakdown, TileAddress


def _write_small_container(path: Path) -> Path:
    writer = McV1Writer(path)
    writer.add_tile(
        TileAddress(0, 0, 0, 2, 2), b"tile-zero", ByteBreakdown(payload=9)
    )
    writer.add_tile(
        TileAddress(0, 2, 0, 2, 2),
        b"tile-one-cert",
        ByteBreakdown(payload=8, certificate=5),
    )
    writer.finalize()
    return path


def test_complete_bytes_equals_file_size(tmp_path: Path) -> None:
    path = _write_small_container(tmp_path / "slide.mcv1")
    ledger = McV1Reader(path).byte_ledger()
    assert ledger.complete_bytes == path.stat().st_size
    assert sum(ledger.categories.values()) == ledger.complete_bytes
    assert ledger.categories["payload"] == 17
    assert ledger.categories["certificate"] == 5
    assert ledger.categories["integrity"] > 0
    assert ledger.categories["index"] > 0


def test_one_tile_read_does_not_read_unrelated_payloads(tmp_path: Path) -> None:
    path = _write_small_container(tmp_path / "three.mcv1")
    reader = McV1Reader(path)
    packet = reader.read_tile(TileAddress(0, 2, 0, 2, 2))
    assert packet == b"tile-one-cert"
    assert reader.payload_reads == [1]


def test_container_bytes_are_deterministic(tmp_path: Path) -> None:
    first = _write_small_container(tmp_path / "a.mcv1")
    second = _write_small_container(tmp_path / "b.mcv1")
    assert first.read_bytes() == second.read_bytes()


def test_writer_requires_sorted_unique_addresses(tmp_path: Path) -> None:
    writer = McV1Writer(tmp_path / "invalid.mcv1")
    writer.add_tile(TileAddress(0, 2, 0, 2, 2), b"a", ByteBreakdown(payload=1))
    try:
        writer.add_tile(TileAddress(0, 0, 0, 2, 2), b"b", ByteBreakdown(payload=1))
    except ValueError as error:
        assert "strictly increasing" in str(error)
    else:
        raise AssertionError("writer accepted an unsorted address")
    writer.abort()
