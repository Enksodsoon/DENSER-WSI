from __future__ import annotations

import hashlib
import struct

import numpy as np

from denser.repair.mask import RepairMask, decode_repair_mask
from denser.repair.residual import (
    apply_exact_residual,
    encode_delta_residual,
    encode_exact_residual,
)


MAGIC = b"R2PK"
HEADER = struct.Struct(">4sII32s")
COMPOSITE_MAGIC = b"R2CP"
COMPOSITE_HEADER = struct.Struct(">4sHI32s")
PART_LENGTH = struct.Struct(">I")


def encode_composite_repair_packet(parts: tuple[bytes, ...]) -> bytes:
    if not 2 <= len(parts) <= 16 or any(
        not part or part.startswith(COMPOSITE_MAGIC) for part in parts
    ):
        raise ValueError("composite repair requires two to sixteen non-composite parts")
    body = b"".join(PART_LENGTH.pack(len(part)) + part for part in parts)
    return COMPOSITE_HEADER.pack(
        COMPOSITE_MAGIC,
        len(parts),
        len(body),
        hashlib.sha256(body).digest(),
    ) + body


def _decode_composite_parts(payload: bytes) -> tuple[bytes, ...]:
    if len(payload) < COMPOSITE_HEADER.size:
        raise ValueError("composite repair packet is truncated")
    magic, count, body_length, digest = COMPOSITE_HEADER.unpack_from(payload)
    body = payload[COMPOSITE_HEADER.size :]
    if (
        magic != COMPOSITE_MAGIC
        or not 2 <= count <= 16
        or len(body) != body_length
        or hashlib.sha256(body).digest() != digest
    ):
        raise ValueError("composite repair packet is invalid")
    parts = []
    offset = 0
    for _index in range(count):
        if offset + PART_LENGTH.size > len(body):
            raise ValueError("composite repair part length is truncated")
        length = PART_LENGTH.unpack_from(body, offset)[0]
        offset += PART_LENGTH.size
        part = body[offset : offset + length]
        if not part or len(part) != length or part.startswith(COMPOSITE_MAGIC):
            raise ValueError("composite repair part is invalid")
        parts.append(part)
        offset += length
    if offset != len(body):
        raise ValueError("composite repair packet has trailing bytes")
    return tuple(parts)


def encode_repair_packet(
    mask: RepairMask, repaired: np.ndarray, *, base: np.ndarray | None = None
) -> bytes:
    pixel_residual = encode_exact_residual(repaired, mask)
    residual = (
        min(
            pixel_residual,
            encode_delta_residual(repaired, base, mask),
            key=lambda value: (len(value), value[:4]),
        )
        if base is not None
        else pixel_residual
    )
    body = mask.encoded + residual
    return HEADER.pack(MAGIC, len(mask.encoded), len(residual), hashlib.sha256(body).digest()) + body


def apply_repair_packet(decoded: np.ndarray, payload: bytes) -> np.ndarray:
    if payload[:4] == COMPOSITE_MAGIC:
        repaired = np.asarray(decoded)
        for part in _decode_composite_parts(payload):
            repaired = apply_repair_packet(repaired, part)
        return repaired
    if payload[:4] == b"R2TO":
        from denser.repair.transform_overlay import apply_transform_overlay

        return apply_transform_overlay(decoded, payload)
    if len(payload) < HEADER.size:
        raise ValueError("repair packet is truncated")
    magic, mask_length, residual_length, digest = HEADER.unpack_from(payload)
    body = payload[HEADER.size:]
    if magic != MAGIC or len(body) != mask_length + residual_length:
        raise ValueError("repair-packet header is invalid")
    if hashlib.sha256(body).digest() != digest:
        raise ValueError("repair-packet digest mismatch")
    mask = decode_repair_mask(body[:mask_length])
    values = np.asarray(decoded)
    if values.shape[:2] != mask.shape:
        raise ValueError("repair packet does not match decoded tile")
    return apply_exact_residual(values, mask, body[mask_length:])
