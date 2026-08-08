from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass

import numpy as np
import zstandard as zstd


MAGIC = b"EAM2"
VERSION = 1
BLOCK_SIZE = 8
PALETTE = (0.25, 0.5, 1.0, 2.0, 4.0)
HEADER = struct.Struct(">4sBBBBHHII32s")
RUN = struct.Struct(">BH")
FREQUENCY_MULTIPLIERS = np.asarray(
    [[min(4.0, 1.0 + (row + column) / 8.0) for column in range(8)] for row in range(8)],
    dtype=np.float64,
)


def _require_zstd_157() -> None:
    if tuple(zstd.ZSTD_VERSION) != (1, 5, 7):
        raise RuntimeError(f"MC-V2 requires zstd 1.5.7, found {zstd.ZSTD_VERSION}")


@dataclass(frozen=True, slots=True)
class EvidenceAllocationMapV2:
    height_blocks: int
    width_blocks: int
    channels: int
    classes: tuple[int, ...]

    def __post_init__(self) -> None:
        if min(self.height_blocks, self.width_blocks) <= 0 or self.channels != 3:
            raise ValueError("allocation-map dimensions or channels are invalid")
        expected = self.height_blocks * self.width_blocks * self.channels
        if len(self.classes) != expected or any(value not in range(len(PALETTE)) for value in self.classes):
            raise ValueError("allocation-map classes are invalid")

    def _rle(self) -> bytes:
        chunks: list[bytes] = []
        index = 0
        while index < len(self.classes):
            value = self.classes[index]
            end = index + 1
            while end < len(self.classes) and self.classes[end] == value and end - index < 65535:
                end += 1
            chunks.append(RUN.pack(value, end - index))
            index = end
        return b"".join(chunks)

    def encode(self) -> bytes:
        _require_zstd_157()
        raw = self._rle()
        compressed = zstd.ZstdCompressor(
            level=7, threads=0, write_checksum=True, write_content_size=True
        ).compress(raw)
        return HEADER.pack(
            MAGIC,
            VERSION,
            BLOCK_SIZE,
            self.channels,
            len(PALETTE),
            self.height_blocks,
            self.width_blocks,
            len(self.classes),
            len(compressed),
            hashlib.sha256(raw).digest(),
        ) + compressed

    @classmethod
    def decode(cls, payload: bytes) -> EvidenceAllocationMapV2:
        if len(payload) < HEADER.size:
            raise ValueError("allocation map is truncated")
        magic, version, block, channels, palette_count, height, width, count, length, digest = HEADER.unpack_from(payload)
        compressed = payload[HEADER.size:]
        if (
            magic != MAGIC
            or version != VERSION
            or block != BLOCK_SIZE
            or channels != 3
            or palette_count != len(PALETTE)
            or count != height * width * channels
            or len(compressed) != length
        ):
            raise ValueError("allocation-map header is invalid")
        _require_zstd_157()
        try:
            raw = zstd.ZstdDecompressor().decompress(compressed, max_output_size=count * RUN.size)
        except zstd.ZstdError as error:
            raise ValueError("allocation-map zstd stream is invalid") from error
        if hashlib.sha256(raw).digest() != digest or len(raw) % RUN.size:
            raise ValueError("allocation-map payload integrity failed")
        values: list[int] = []
        for offset in range(0, len(raw), RUN.size):
            value, run = RUN.unpack_from(raw, offset)
            if value >= len(PALETTE) or run == 0 or (values and values[-1] == value):
                raise ValueError("allocation-map RLE is noncanonical")
            values.extend([value] * run)
            if len(values) > count:
                raise ValueError("allocation-map RLE exceeds declared size")
        if len(values) != count:
            raise ValueError("allocation-map RLE is incomplete")
        result = cls(height, width, channels, tuple(values))
        if result.encode() != payload:
            raise ValueError("allocation-map encoding is noncanonical")
        return result

    def coefficient_steps(self, base_step: float, shape: tuple[int, int, int]) -> np.ndarray:
        if not math.isfinite(base_step) or base_step <= 0 or shape[2] != self.channels:
            raise ValueError("coefficient-step request is invalid")
        expected = (self.height_blocks * BLOCK_SIZE, self.width_blocks * BLOCK_SIZE, self.channels)
        if shape != expected:
            raise ValueError("coefficient shape does not match allocation map")
        classes = np.asarray(self.classes, dtype=np.uint8).reshape(
            self.height_blocks, self.width_blocks, self.channels
        )
        result = np.empty(shape, dtype=np.float64)
        for block_y in range(self.height_blocks):
            for block_x in range(self.width_blocks):
                for channel in range(self.channels):
                    multiplier = PALETTE[int(classes[block_y, block_x, channel])]
                    result[
                        block_y * BLOCK_SIZE : (block_y + 1) * BLOCK_SIZE,
                        block_x * BLOCK_SIZE : (block_x + 1) * BLOCK_SIZE,
                        channel,
                    ] = base_step * multiplier * FREQUENCY_MULTIPLIERS
        return result


def build_evidence_allocation_map(sensitivity: np.ndarray) -> EvidenceAllocationMapV2:
    values = np.asarray(sensitivity, dtype=np.float64)
    if values.ndim != 3 or values.shape[2] != 3 or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("sensitivity must be finite non-negative RGB data")
    height_blocks = math.ceil(values.shape[0] / BLOCK_SIZE)
    width_blocks = math.ceil(values.shape[1] / BLOCK_SIZE)
    padded = np.pad(
        values,
        ((0, height_blocks * BLOCK_SIZE - values.shape[0]), (0, width_blocks * BLOCK_SIZE - values.shape[1]), (0, 0)),
        mode="edge",
    )
    block_values = padded.reshape(height_blocks, BLOCK_SIZE, width_blocks, BLOCK_SIZE, 3).mean(axis=(1, 3))
    normalizer = max(float(np.median(np.maximum(block_values, 1e-12))), 1e-12)
    desired = 1.0 / np.sqrt(np.maximum(block_values, 1e-12) / normalizer)
    log_palette = np.log2(np.asarray(PALETTE))
    classes = np.abs(np.log2(np.clip(desired, PALETTE[0], PALETTE[-1]))[..., None] - log_palette).argmin(axis=-1)
    return EvidenceAllocationMapV2(height_blocks, width_blocks, 3, tuple(int(value) for value in classes.ravel()))
