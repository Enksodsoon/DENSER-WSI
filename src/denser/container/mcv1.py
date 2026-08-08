from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path

from denser.container.index import INDEX_ENTRY_STRUCT, IndexEntry, pack_index, unpack_index
from denser.container.ledger import SlideByteLedger
from denser.core.canonical import canonical_json_bytes
from denser.core.models import ByteBreakdown, TileAddress


MAGIC = b"MCV1\r\n\x1a\n"
VERSION = 1
HEADER_STRUCT = struct.Struct(">8sHHI12Q32s32s")
HEADER_SIZE = HEADER_STRUCT.size
OVERVIEW = b"{}"
PACKET_CATEGORIES = {
    "payload",
    "repair",
    "certificate",
    "reference_evidence",
    "method_signaling",
    "fallback_signaling",
}


class McV1CorruptionError(RuntimeError):
    """MC-V1 bytes violate a structural or cryptographic invariant."""


def _align(value: int, boundary: int = 8) -> int:
    return (value + boundary - 1) // boundary * boundary


class McV1Writer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._temporary = path.with_name(f".{path.name}.building")
        self._stream = self._temporary.open("w+b")
        overview_offset = HEADER_SIZE
        self._packet_offset = _align(overview_offset + len(OVERVIEW))
        self._stream.write(b"\x00" * HEADER_SIZE)
        self._stream.write(OVERVIEW)
        self._stream.write(b"\x00" * (self._packet_offset - self._stream.tell()))
        self._entries: list[IndexEntry] = []
        self._packet_digests: list[bytes] = []
        self._last_address: TileAddress | None = None
        self._closed = False

    def add_tile(
        self, address: TileAddress, packet: bytes, breakdown: ByteBreakdown
    ) -> None:
        if self._closed:
            raise RuntimeError("MC-V1 writer is closed")
        if self._last_address is not None and address <= self._last_address:
            raise ValueError("tile addresses must be strictly increasing")
        if breakdown.complete != len(packet):
            raise ValueError("packet byte breakdown must equal packet length")
        for name in ByteBreakdown.__dataclass_fields__:
            if name not in PACKET_CATEGORIES and getattr(breakdown, name):
                raise ValueError(f"{name} is a container-level byte category")
        packet_offset = self._stream.tell()
        self._stream.write(packet)
        self._entries.append(IndexEntry(address, packet_offset, len(packet), breakdown))
        self._packet_digests.append(hashlib.sha256(packet).digest())
        self._last_address = address

    def finalize(self) -> None:
        if self._closed:
            raise RuntimeError("MC-V1 writer is closed")
        entries = tuple(self._entries)
        packet_length = self._stream.tell() - self._packet_offset
        index_offset = self._stream.tell()
        index = pack_index(entries)
        self._stream.write(index)
        integrity_offset = self._stream.tell()
        integrity = b"".join(self._packet_digests) + hashlib.sha256(index).digest()
        self._stream.write(integrity)
        manifest_offset = self._stream.tell()
        manifest = canonical_json_bytes(
            {
                "format": "MC-V1",
                "tile_count": len(entries),
                "overview_sha256": hashlib.sha256(OVERVIEW).hexdigest(),
                "integrity_sha256": hashlib.sha256(integrity).hexdigest(),
                "index_entry_size": INDEX_ENTRY_STRUCT.size,
            }
        )
        self._stream.write(manifest)
        file_size = self._stream.tell()
        fields = (
            MAGIC,
            VERSION,
            HEADER_SIZE,
            len(entries),
            HEADER_SIZE,
            len(OVERVIEW),
            self._packet_offset,
            packet_length,
            index_offset,
            len(index),
            integrity_offset,
            len(integrity),
            manifest_offset,
            len(manifest),
            file_size,
            0,
        )
        manifest_digest = hashlib.sha256(manifest).digest()
        unsigned_header = HEADER_STRUCT.pack(
            *fields, b"\x00" * 32, manifest_digest
        )
        header_digest = hashlib.sha256(unsigned_header).digest()
        header = HEADER_STRUCT.pack(*fields, header_digest, manifest_digest)
        self._stream.seek(0)
        self._stream.write(header)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        os.replace(self._temporary, self.path)
        self._closed = True

    def abort(self) -> None:
        if not self._closed:
            self._stream.close()
            self._temporary.unlink(missing_ok=True)
            self._closed = True


class McV1Reader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.payload_reads: list[int] = []
        try:
            self._load_structure()
        except (OSError, ValueError, struct.error, json.JSONDecodeError) as error:
            if isinstance(error, McV1CorruptionError):
                raise
            raise McV1CorruptionError(str(error)) from error

    @staticmethod
    def _read_exact(stream, offset: int, length: int) -> bytes:  # type: ignore[no-untyped-def]
        stream.seek(offset)
        data = stream.read(length)
        if len(data) != length:
            raise McV1CorruptionError("container is truncated")
        return data

    def _load_structure(self) -> None:
        actual_size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            raw_header = self._read_exact(stream, 0, HEADER_SIZE)
            unpacked = HEADER_STRUCT.unpack(raw_header)
            if unpacked[0] != MAGIC or unpacked[1] != VERSION or unpacked[2] != HEADER_SIZE:
                raise McV1CorruptionError("header identity is invalid")
            tile_count = unpacked[3]
            section_values = unpacked[4:16]
            (
                overview_offset,
                overview_length,
                packet_offset,
                packet_length,
                index_offset,
                index_length,
                integrity_offset,
                integrity_length,
                manifest_offset,
                manifest_length,
                declared_size,
                reserved,
            ) = section_values
            header_digest, manifest_digest = unpacked[16:18]
            unsigned = HEADER_STRUCT.pack(
                *unpacked[:16], b"\x00" * 32, manifest_digest
            )
            if hashlib.sha256(unsigned).digest() != header_digest:
                raise McV1CorruptionError("header digest mismatch")
            if reserved != 0 or declared_size != actual_size:
                raise McV1CorruptionError("header file length mismatch")
            if not (
                overview_offset == HEADER_SIZE
                and overview_offset + overview_length <= packet_offset
                and packet_offset + packet_length == index_offset
                and index_offset + index_length == integrity_offset
                and integrity_offset + integrity_length == manifest_offset
                and manifest_offset + manifest_length == declared_size
            ):
                raise McV1CorruptionError("header section layout is invalid")
            overview = self._read_exact(stream, overview_offset, overview_length)
            if hashlib.sha256(overview).digest() != hashlib.sha256(OVERVIEW).digest():
                raise McV1CorruptionError("overview digest mismatch")
            padding = self._read_exact(
                stream, overview_offset + overview_length, packet_offset - overview_offset - overview_length
            )
            if any(padding):
                raise McV1CorruptionError("padding is nonzero")
            index = self._read_exact(stream, index_offset, index_length)
            integrity = self._read_exact(stream, integrity_offset, integrity_length)
            manifest = self._read_exact(stream, manifest_offset, manifest_length)
        if hashlib.sha256(manifest).digest() != manifest_digest:
            raise McV1CorruptionError("manifest digest mismatch")
        document = json.loads(manifest)
        if document.get("format") != "MC-V1" or document.get("tile_count") != tile_count:
            raise McV1CorruptionError("manifest semantics are invalid")
        if document.get("integrity_sha256") != hashlib.sha256(integrity).hexdigest():
            raise McV1CorruptionError("integrity section digest mismatch")
        expected_integrity_length = (tile_count + 1) * 32
        if integrity_length != expected_integrity_length:
            raise McV1CorruptionError("integrity section length is invalid")
        if hashlib.sha256(index).digest() != integrity[-32:]:
            raise McV1CorruptionError("index digest mismatch")
        try:
            entries = unpack_index(index, tile_count)
        except ValueError as error:
            raise McV1CorruptionError(str(error)) from error
        for entry in entries:
            if not (
                packet_offset <= entry.offset
                and entry.offset + entry.length <= packet_offset + packet_length
                and entry.breakdown.complete == entry.length
            ):
                raise McV1CorruptionError("index packet bounds are invalid")
        self.packet_region_offset = packet_offset
        self.packet_region_length = packet_length
        self.index_offset = index_offset
        self.index_length = index_length
        self.integrity_offset = integrity_offset
        self.integrity_length = integrity_length
        self.manifest_offset = manifest_offset
        self.manifest_length = manifest_length
        self.overview_length = overview_length
        self.padding_length = packet_offset - overview_offset - overview_length
        self._entries = entries
        self._by_address = {entry.address: index for index, entry in enumerate(entries)}
        self._packet_digests = tuple(
            integrity[index : index + 32] for index in range(0, tile_count * 32, 32)
        )

    def read_tile(self, address: TileAddress) -> bytes:
        try:
            ordinal = self._by_address[address]
        except KeyError as error:
            raise KeyError("tile address is absent from MC-V1 index") from error
        entry = self._entries[ordinal]
        with self.path.open("rb") as stream:
            packet = self._read_exact(stream, entry.offset, entry.length)
        self.payload_reads.append(ordinal)
        if hashlib.sha256(packet).digest() != self._packet_digests[ordinal]:
            raise McV1CorruptionError("packet digest mismatch")
        return packet

    decode_tile = read_tile

    def byte_ledger(self) -> SlideByteLedger:
        categories = {name: 0 for name in ByteBreakdown.__dataclass_fields__}
        for entry in self._entries:
            for name in categories:
                categories[name] += getattr(entry.breakdown, name)
        categories["header"] += HEADER_SIZE
        categories["overview"] += self.overview_length
        categories["padding"] += self.padding_length
        categories["index"] += self.index_length
        categories["integrity"] += self.integrity_length
        categories["metadata"] += self.manifest_length
        return SlideByteLedger(categories)
