from __future__ import annotations

import struct
import zlib

import numpy as np

from denser.repair.mask import RepairMask


_HEADER = struct.Struct(">4sI")


def encode_exact_residual(source: np.ndarray, mask: RepairMask) -> bytes:
    pixels = np.asarray(source)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("source must be uint8 RGB")
    if pixels.shape[:2] != mask.shape:
        raise ValueError("source and repair mask shapes differ")
    selected = np.ascontiguousarray(pixels[mask.pixels]).tobytes()
    compressed = zlib.compress(selected, level=9)
    return _HEADER.pack(b"RPV1", mask.pixel_count) + compressed


def encode_delta_residual(
    source: np.ndarray, base: np.ndarray, mask: RepairMask
) -> bytes:
    pixels = np.asarray(source)
    decoded = np.asarray(base)
    if (
        pixels.dtype != np.uint8
        or decoded.dtype != np.uint8
        or pixels.shape != decoded.shape
        or pixels.ndim != 3
        or pixels.shape[2] != 3
        or pixels.shape[:2] != mask.shape
    ):
        raise ValueError("delta residual requires matching uint8 RGB pixels and mask")
    delta = (
        pixels[mask.pixels].astype(np.int16)
        - decoded[mask.pixels].astype(np.int16)
    ).astype(">i2", copy=False)
    compressed = zlib.compress(np.ascontiguousarray(delta).tobytes(), level=9)
    return _HEADER.pack(b"RPD2", mask.pixel_count) + compressed


def apply_exact_residual(
    decoded: np.ndarray, mask: RepairMask, payload: bytes
) -> np.ndarray:
    if len(payload) < _HEADER.size:
        raise ValueError("residual payload is truncated")
    magic, count = _HEADER.unpack_from(payload)
    if magic not in (b"RPV1", b"RPD2") or count != mask.pixel_count:
        raise ValueError("residual payload metadata is invalid")
    try:
        raw = zlib.decompress(payload[_HEADER.size :])
    except zlib.error as error:
        raise ValueError("residual payload is corrupt") from error
    repaired = np.asarray(decoded).copy()
    if magic == b"RPV1":
        if len(raw) != count * 3:
            raise ValueError("residual payload length is invalid")
        repaired[mask.pixels] = np.frombuffer(raw, dtype=np.uint8).reshape(count, 3)
    else:
        if len(raw) != count * 3 * 2:
            raise ValueError("delta residual payload length is invalid")
        values = repaired[mask.pixels].astype(np.int16) + np.frombuffer(
            raw, dtype=">i2"
        ).astype(np.int16).reshape(count, 3)
        if np.any(values < 0) or np.any(values > 255):
            raise ValueError("delta residual reconstructs pixels outside uint8")
        repaired[mask.pixels] = values.astype(np.uint8)
    return repaired
