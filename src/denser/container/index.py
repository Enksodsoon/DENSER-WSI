from __future__ import annotations

import struct
from dataclasses import dataclass

from denser.core.models import ByteBreakdown, TileAddress


BREAKDOWN_FIELDS = tuple(ByteBreakdown.__dataclass_fields__)
INDEX_ENTRY_STRUCT = struct.Struct(">IQQIIQQ12Q")


@dataclass(frozen=True, slots=True)
class IndexEntry:
    address: TileAddress
    offset: int
    length: int
    breakdown: ByteBreakdown


def pack_index(entries: tuple[IndexEntry, ...]) -> bytes:
    chunks = []
    for entry in entries:
        address = entry.address
        chunks.append(
            INDEX_ENTRY_STRUCT.pack(
                address.level,
                address.x,
                address.y,
                address.width,
                address.height,
                entry.offset,
                entry.length,
                *(getattr(entry.breakdown, name) for name in BREAKDOWN_FIELDS),
            )
        )
    return b"".join(chunks)


def unpack_index(data: bytes, count: int) -> tuple[IndexEntry, ...]:
    if len(data) != count * INDEX_ENTRY_STRUCT.size:
        raise ValueError("index length does not match tile count")
    entries = []
    for offset in range(0, len(data), INDEX_ENTRY_STRUCT.size):
        values = INDEX_ENTRY_STRUCT.unpack_from(data, offset)
        address = TileAddress(values[0], values[1], values[2], values[3], values[4])
        breakdown = ByteBreakdown(
            **dict(zip(BREAKDOWN_FIELDS, values[7:], strict=True))
        )
        entries.append(IndexEntry(address, values[5], values[6], breakdown))
    if tuple(entry.address for entry in entries) != tuple(
        sorted(entry.address for entry in entries)
    ):
        raise ValueError("index addresses are not sorted")
    if len({entry.address for entry in entries}) != len(entries):
        raise ValueError("index contains duplicate addresses")
    return tuple(entries)
