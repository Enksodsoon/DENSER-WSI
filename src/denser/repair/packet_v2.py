from __future__ import annotations

import hashlib
import struct

import numpy as np

from denser.repair.mask import RepairMask, decode_repair_mask
from denser.repair.residual import apply_exact_residual, encode_exact_residual


MAGIC = b"R2PK"
HEADER = struct.Struct(">4sII32s")


def encode_repair_packet(mask: RepairMask, repaired: np.ndarray) -> bytes:
    residual = encode_exact_residual(repaired, mask)
    body = mask.encoded + residual
    return HEADER.pack(MAGIC, len(mask.encoded), len(residual), hashlib.sha256(body).digest()) + body


def apply_repair_packet(decoded: np.ndarray, payload: bytes) -> np.ndarray:
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
