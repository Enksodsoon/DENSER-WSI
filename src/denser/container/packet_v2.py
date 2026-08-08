from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass

from denser.core.models import ByteBreakdown


MAGIC = b"M2TP"
VERSION = 1
HEADER = struct.Struct(">4sBBHH4I32s")
_CODEC_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


@dataclass(frozen=True, slots=True)
class McV2TilePacket:
    codec_id: str
    profile_id: str
    allocation_map: bytes
    payload: bytes
    repair: bytes
    certificate: bytes
    fallback: bool

    def __post_init__(self) -> None:
        if _CODEC_ID.fullmatch(self.codec_id) is None or not self.profile_id or len(self.profile_id) > 127:
            raise ValueError("MC-V2 codec or profile identity is invalid")
        if not self.payload or not self.certificate:
            raise ValueError("MC-V2 payload and certificate are required")

    def encode(self) -> bytes:
        codec = self.codec_id.encode("ascii")
        try:
            profile = self.profile_id.encode("ascii")
        except UnicodeEncodeError as error:
            raise ValueError("MC-V2 profile identity is not ASCII") from error
        body = codec + profile + self.allocation_map + self.payload + self.repair + self.certificate
        return HEADER.pack(
            MAGIC,
            VERSION,
            int(self.fallback),
            len(codec),
            len(profile),
            len(self.allocation_map),
            len(self.payload),
            len(self.repair),
            len(self.certificate),
            hashlib.sha256(body).digest(),
        ) + body

    @classmethod
    def decode(cls, encoded: bytes) -> McV2TilePacket:
        if len(encoded) < HEADER.size:
            raise ValueError("MC-V2 tile packet is truncated")
        magic, version, flags, codec_length, profile_length, allocation_length, payload_length, repair_length, certificate_length, digest = HEADER.unpack_from(encoded)
        total = codec_length + profile_length + allocation_length + payload_length + repair_length + certificate_length
        body = encoded[HEADER.size:]
        if magic != MAGIC or version != VERSION or flags not in (0, 1) or len(body) != total:
            raise ValueError("MC-V2 tile packet header is invalid")
        if hashlib.sha256(body).digest() != digest:
            raise ValueError("MC-V2 tile packet digest mismatch")
        cursor = 0
        sections = []
        for length in (codec_length, profile_length, allocation_length, payload_length, repair_length, certificate_length):
            sections.append(body[cursor : cursor + length])
            cursor += length
        try:
            codec_id = sections[0].decode("ascii")
            profile_id = sections[1].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("MC-V2 codec identity is not ASCII") from error
        return cls(
            codec_id, profile_id, sections[2], sections[3], sections[4], sections[5], bool(flags)
        )

    def breakdown(self) -> ByteBreakdown:
        signaling = (
            HEADER.size
            + len(self.codec_id.encode("ascii"))
            + len(self.profile_id.encode("ascii"))
            + len(self.allocation_map)
        )
        fallback_bytes = 1 if self.fallback else 0
        return ByteBreakdown(
            payload=len(self.payload),
            repair=len(self.repair),
            certificate=len(self.certificate),
            method_signaling=signaling - fallback_bytes,
            fallback_signaling=fallback_bytes,
        )
