from __future__ import annotations

import hashlib
import struct
import zlib

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.core.models import ByteBreakdown


MAGIC = b"LSV1"
HEADER = struct.Struct(">4sBIII32s")


class LosslessIntegrityError(RuntimeError):
    """The shared fallback packet failed shape or digest validation."""


def _validate_rgb(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("fallback input must be uint8 RGB")
    return np.ascontiguousarray(pixels)


def _forward_transform(rgb: np.ndarray) -> np.ndarray:
    values = rgb.astype(np.int16)
    transformed = np.empty_like(rgb)
    transformed[:, :, 0] = values[:, :, 1]
    transformed[:, :, 1] = (values[:, :, 0] - values[:, :, 1]) & 0xFF
    transformed[:, :, 2] = (values[:, :, 2] - values[:, :, 1]) & 0xFF
    return transformed


def _reverse_transform(transformed: np.ndarray) -> np.ndarray:
    values = transformed.astype(np.int16)
    rgb = np.empty_like(transformed)
    rgb[:, :, 1] = values[:, :, 0]
    rgb[:, :, 0] = (values[:, :, 1] + values[:, :, 0]) & 0xFF
    rgb[:, :, 2] = (values[:, :, 2] + values[:, :, 0]) & 0xFF
    return rgb


class SharedLosslessCodec:
    codec_id = "lossless-zlib-fixed"
    profile_id = "fallback-v1-rct-zlib-fixed-9"

    def encode(self, rgb: np.ndarray) -> EncodedCandidate:
        pixels = _validate_rgb(rgb)
        raw = pixels.tobytes(order="C")
        transformed = _forward_transform(pixels).tobytes(order="C")
        compressor = zlib.compressobj(
            level=9, method=zlib.DEFLATED, wbits=-15, memLevel=9, strategy=zlib.Z_FIXED
        )
        compressed = compressor.compress(transformed) + compressor.flush(zlib.Z_FINISH)
        height, width, channels = pixels.shape
        header = HEADER.pack(
            MAGIC, 1, height, width, channels, hashlib.sha256(raw).digest()
        )
        payload = header + compressed
        return EncodedCandidate(
            self.codec_id,
            self.profile_id,
            payload,
            ByteBreakdown(payload=len(payload)),
        )

    def decode(self, payload: bytes, shape: tuple[int, int, int]) -> np.ndarray:
        if len(payload) < HEADER.size:
            raise LosslessIntegrityError("fallback packet is truncated")
        magic, transform, height, width, channels, digest = HEADER.unpack_from(payload)
        if magic != MAGIC or transform != 1:
            raise LosslessIntegrityError("fallback packet header is invalid")
        stored_shape = (height, width, channels)
        if stored_shape != shape:
            raise LosslessIntegrityError("fallback packet shape mismatch")
        try:
            decompressor = zlib.decompressobj(wbits=-15)
            raw_transform = decompressor.decompress(payload[HEADER.size:])
            raw_transform += decompressor.flush()
        except zlib.error as error:
            raise LosslessIntegrityError("fallback compressed bytes are invalid") from error
        if decompressor.unused_data or decompressor.unconsumed_tail or not decompressor.eof:
            raise LosslessIntegrityError("fallback compressed stream is not canonical")
        if len(raw_transform) != height * width * channels:
            raise LosslessIntegrityError("fallback decoded length mismatch")
        transformed = np.frombuffer(raw_transform, dtype=np.uint8).reshape(stored_shape)
        rgb = _reverse_transform(transformed)
        if hashlib.sha256(rgb.tobytes(order="C")).digest() != digest:
            raise LosslessIntegrityError("fallback pixel digest mismatch")
        return rgb
