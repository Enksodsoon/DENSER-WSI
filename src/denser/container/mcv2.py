from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

from denser.container.index import INDEX_ENTRY_STRUCT, IndexEntry, pack_index, unpack_index
from denser.container.ledger import SlideByteLedger
from denser.core.models import ByteBreakdown, TileAddress


MAGIC = b"MCV2\r\n\x1a\n"
VERSION = 2
HEADER = struct.Struct(">8sHHI8Q32s32s")
JOURNAL_MAGIC = b"MCV2J1\r\n"
JOURNAL_HEADER = struct.Struct(">8s32sQ")
JOURNAL_RECORD_SIZE = INDEX_ENTRY_STRUCT.size + 32


class McV2CorruptionError(RuntimeError):
    """MC-V2 bytes violate a structural or cryptographic invariant."""


class McV2Writer:
    def __init__(self, path: Path, *, resume_token: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._temporary = self.path.with_name(f".{self.path.name}.building")
        self._journal_path = self._temporary.with_name(f"{self._temporary.name}.journal")
        self._entries: list[IndexEntry] = []
        self._digests: list[bytes] = []
        self._last: TileAddress | None = None
        self._closed = False
        self._resume_digest = (
            hashlib.sha256(resume_token.encode("utf-8")).digest()
            if resume_token is not None
            else None
        )
        self._journal = None
        self._committed_count = 0
        if self.path.exists():
            raise RuntimeError("MC-V2 destination already exists")
        if self._resume_digest is None:
            self._stream = self._temporary.open("w+b")
            self._stream.write(b"\0" * HEADER.size)
        elif self._temporary.exists() or self._journal_path.exists():
            self._resume_existing()
        else:
            self._stream = self._temporary.open("x+b")
            self._stream.write(b"\0" * HEADER.size)
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._journal = self._journal_path.open("x+b")
            self._journal.write(JOURNAL_HEADER.pack(JOURNAL_MAGIC, self._resume_digest, 0))
            self._journal.flush()
            os.fsync(self._journal.fileno())

    def _resume_existing(self) -> None:
        if not self._temporary.is_file() or not self._journal_path.is_file():
            raise McV2CorruptionError("MC-V2 resumable state is incomplete")
        self._journal = self._journal_path.open("r+b")
        raw_header = self._journal.read(JOURNAL_HEADER.size)
        try:
            magic, identity, committed_count = JOURNAL_HEADER.unpack(raw_header)
        except struct.error as error:
            raise McV2CorruptionError("MC-V2 resume journal header is invalid") from error
        if magic != JOURNAL_MAGIC or identity != self._resume_digest:
            raise McV2CorruptionError("MC-V2 resume identity mismatch")
        expected_length = JOURNAL_HEADER.size + committed_count * JOURNAL_RECORD_SIZE
        if self._journal_path.stat().st_size < expected_length:
            raise McV2CorruptionError("MC-V2 resume journal is truncated")
        self._journal.seek(JOURNAL_HEADER.size)
        index_chunks: list[bytes] = []
        digests: list[bytes] = []
        for _ordinal in range(committed_count):
            record = self._journal.read(JOURNAL_RECORD_SIZE)
            index_chunks.append(record[: INDEX_ENTRY_STRUCT.size])
            digests.append(record[INDEX_ENTRY_STRUCT.size :])
        try:
            entries = unpack_index(b"".join(index_chunks), committed_count)
        except ValueError as error:
            raise McV2CorruptionError("MC-V2 resume journal index is invalid") from error
        expected_offset = HEADER.size
        with self._temporary.open("rb") as source:
            for entry, digest in zip(entries, digests, strict=True):
                if entry.offset != expected_offset or entry.breakdown.complete != entry.length:
                    raise McV2CorruptionError("MC-V2 resume packet layout is invalid")
                source.seek(entry.offset)
                packet = source.read(entry.length)
                if len(packet) != entry.length or hashlib.sha256(packet).digest() != digest:
                    raise McV2CorruptionError("MC-V2 resume packet digest mismatch")
                expected_offset += entry.length
        self._stream = self._temporary.open("r+b")
        self._stream.truncate(expected_offset)
        self._stream.seek(expected_offset)
        self._journal.truncate(expected_length)
        self._journal.seek(expected_length)
        self._entries = list(entries)
        self._digests = digests
        self._last = entries[-1].address if entries else None
        self._committed_count = committed_count

    @property
    def checkpointed_addresses(self) -> tuple[TileAddress, ...]:
        return tuple(entry.address for entry in self._entries[: self._committed_count])

    def add_tile(self, address: TileAddress, packet: bytes, breakdown: ByteBreakdown) -> None:
        if self._closed:
            raise RuntimeError("MC-V2 writer is closed")
        if self._last is not None and address <= self._last:
            raise ValueError("MC-V2 tile addresses must be strictly increasing")
        if breakdown.complete != len(packet):
            raise ValueError("MC-V2 packet ledger does not equal packet bytes")
        offset = self._stream.tell()
        self._stream.write(packet)
        self._entries.append(IndexEntry(address, offset, len(packet), breakdown))
        digest = hashlib.sha256(packet).digest()
        self._digests.append(digest)
        if self._journal is not None:
            self._journal.write(pack_index((self._entries[-1],)) + digest)
        self._last = address

    def checkpoint(self) -> None:
        if self._closed:
            raise RuntimeError("MC-V2 writer is closed")
        if self._journal is None or self._committed_count == len(self._entries):
            return
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._journal.flush()
        os.fsync(self._journal.fileno())
        self._committed_count = len(self._entries)
        self._journal.seek(0)
        self._journal.write(
            JOURNAL_HEADER.pack(
                JOURNAL_MAGIC, self._resume_digest, self._committed_count
            )
        )
        self._journal.flush()
        os.fsync(self._journal.fileno())
        self._journal.seek(0, os.SEEK_END)

    def rollback_to_checkpoint(self, count: int) -> None:
        if self._closed or self._journal is None:
            raise RuntimeError("MC-V2 rollback requires an open resumable writer")
        if not 0 <= count <= self._committed_count:
            raise ValueError("MC-V2 rollback count is outside committed state")
        if count == self._committed_count:
            return
        entries = self._entries[:count]
        packet_end = entries[-1].offset + entries[-1].length if entries else HEADER.size
        journal_end = JOURNAL_HEADER.size + count * JOURNAL_RECORD_SIZE
        self._stream.truncate(packet_end)
        self._stream.seek(packet_end)
        self._entries = entries
        self._digests = self._digests[:count]
        self._last = entries[-1].address if entries else None
        self._committed_count = count
        self._journal.truncate(journal_end)
        self._journal.seek(0)
        self._journal.write(
            JOURNAL_HEADER.pack(JOURNAL_MAGIC, self._resume_digest, count)
        )
        self._journal.flush()
        os.fsync(self._journal.fileno())
        self._journal.seek(journal_end)

    def suspend(self) -> None:
        if self._closed:
            return
        self.checkpoint()
        self._stream.close()
        if self._journal is not None:
            self._journal.close()
        self._closed = True

    def finalize(self) -> None:
        if self._closed:
            raise RuntimeError("MC-V2 writer is closed")
        self.checkpoint()
        packet_offset = HEADER.size
        packet_length = self._stream.tell() - packet_offset
        index_offset = self._stream.tell()
        index = pack_index(tuple(self._entries))
        self._stream.write(index)
        integrity_offset = self._stream.tell()
        integrity = b"".join(self._digests) + hashlib.sha256(index).digest()
        self._stream.write(integrity)
        file_size = self._stream.tell()
        fields = (
            MAGIC, VERSION, HEADER.size, len(self._entries), packet_offset, packet_length,
            index_offset, len(index), integrity_offset, len(integrity), file_size, 0,
        )
        integrity_digest = hashlib.sha256(integrity).digest()
        unsigned = HEADER.pack(*fields, b"\0" * 32, integrity_digest)
        header = HEADER.pack(*fields, hashlib.sha256(unsigned).digest(), integrity_digest)
        self._stream.seek(0)
        self._stream.write(header)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        if self._journal is not None:
            self._journal.close()
        os.replace(self._temporary, self.path)
        self._journal_path.unlink(missing_ok=True)
        self._closed = True

    def abort(self) -> None:
        if not self._closed:
            self._stream.close()
            if self._journal is not None:
                self._journal.close()
            self._temporary.unlink(missing_ok=True)
            self._journal_path.unlink(missing_ok=True)
            self._closed = True


class McV2Reader:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.payload_reads: list[int] = []
        try:
            self._load()
        except (OSError, ValueError, struct.error) as error:
            if isinstance(error, McV2CorruptionError):
                raise
            raise McV2CorruptionError(str(error)) from error

    @staticmethod
    def _read_exact(stream, offset: int, length: int) -> bytes:  # type: ignore[no-untyped-def]
        stream.seek(offset)
        value = stream.read(length)
        if len(value) != length:
            raise McV2CorruptionError("MC-V2 container is truncated")
        return value

    def _load(self) -> None:
        actual_size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            raw = self._read_exact(stream, 0, HEADER.size)
            values = HEADER.unpack(raw)
            if values[:3] != (MAGIC, VERSION, HEADER.size):
                raise McV2CorruptionError("MC-V2 header identity is invalid")
            tile_count = values[3]
            packet_offset, packet_length, index_offset, index_length, integrity_offset, integrity_length, file_size, reserved = values[4:12]
            header_digest, integrity_digest = values[12:14]
            unsigned = HEADER.pack(*values[:12], b"\0" * 32, integrity_digest)
            if hashlib.sha256(unsigned).digest() != header_digest:
                raise McV2CorruptionError("MC-V2 header digest mismatch")
            if reserved or file_size != actual_size or not (
                packet_offset == HEADER.size
                and packet_offset + packet_length == index_offset
                and index_offset + index_length == integrity_offset
                and integrity_offset + integrity_length == file_size
            ):
                raise McV2CorruptionError("MC-V2 section layout is invalid")
            index = self._read_exact(stream, index_offset, index_length)
            integrity = self._read_exact(stream, integrity_offset, integrity_length)
        if hashlib.sha256(integrity).digest() != integrity_digest:
            raise McV2CorruptionError("MC-V2 integrity digest mismatch")
        if integrity_length != (tile_count + 1) * 32 or hashlib.sha256(index).digest() != integrity[-32:]:
            raise McV2CorruptionError("MC-V2 index integrity mismatch")
        entries = unpack_index(index, tile_count)
        for entry in entries:
            if not (
                packet_offset <= entry.offset
                and entry.offset + entry.length <= index_offset
                and entry.breakdown.complete == entry.length
            ):
                raise McV2CorruptionError("MC-V2 packet bounds are invalid")
        self.packet_region_offset = packet_offset
        self.packet_region_length = packet_length
        self.index_offset = index_offset
        self.index_length = index_length
        self.integrity_offset = integrity_offset
        self.integrity_length = integrity_length
        self._entries = entries
        self._by_address = {entry.address: ordinal for ordinal, entry in enumerate(entries)}
        self._packet_digests = tuple(integrity[offset : offset + 32] for offset in range(0, tile_count * 32, 32))

    def read_tile(self, address: TileAddress) -> bytes:
        try:
            ordinal = self._by_address[address]
        except KeyError as error:
            raise KeyError("tile address is absent from MC-V2 index") from error
        entry = self._entries[ordinal]
        with self.path.open("rb") as stream:
            packet = self._read_exact(stream, entry.offset, entry.length)
        self.payload_reads.append(ordinal)
        if hashlib.sha256(packet).digest() != self._packet_digests[ordinal]:
            raise McV2CorruptionError("MC-V2 packet digest mismatch")
        return packet

    @property
    def addresses(self) -> tuple[TileAddress, ...]:
        return tuple(entry.address for entry in self._entries)

    @property
    def tile_count(self) -> int:
        return len(self._entries)

    def byte_ledger(self) -> SlideByteLedger:
        categories = {name: 0 for name in ByteBreakdown.__dataclass_fields__}
        for entry in self._entries:
            for name in categories:
                categories[name] += getattr(entry.breakdown, name)
        categories["header"] += HEADER.size
        categories["index"] += self.index_length
        categories["integrity"] += self.integrity_length
        return SlideByteLedger(categories)
