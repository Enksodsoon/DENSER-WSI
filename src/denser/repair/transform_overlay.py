from __future__ import annotations

import hashlib
from functools import lru_cache
import math
import struct

import numpy as np

from denser.repair.mask import RepairMask, decode_repair_mask


MAGIC = b"R2TO"
HEADER = struct.Struct(">4sHHBBBII32s")
COEFFICIENT = struct.Struct(">Hh")
QUANTIZATION_STEPS = (0.5, 1.0, 2.0, 4.0)
COEFFICIENT_COUNTS = (0, 4, 16, 64)


@lru_cache(maxsize=8)
def _dct_matrix(size: int) -> np.ndarray:
    positions = np.arange(size, dtype=np.float64)
    frequencies = positions[:, None]
    matrix = np.cos(np.pi * (2 * positions + 1) * frequencies / (2 * size))
    matrix[0] *= math.sqrt(1 / size)
    matrix[1:] *= math.sqrt(2 / size)
    matrix.flags.writeable = False
    return matrix


def _blocks(mask: np.ndarray, block_size: int) -> tuple[tuple[int, int], ...]:
    height, width = mask.shape
    return tuple(
        (y, x)
        for y in range(0, height, block_size)
        for x in range(0, width, block_size)
        if np.any(mask[y : y + block_size, x : x + block_size])
    )


def _step_code(step: float) -> int:
    if not math.isfinite(step):
        raise ValueError("overlay quantization step must be finite")
    try:
        return QUANTIZATION_STEPS.index(float(step))
    except ValueError as error:
        raise ValueError("overlay quantization step is not predeclared") from error


def encode_transform_overlay(
    source: np.ndarray,
    proposal: np.ndarray,
    mask: RepairMask,
    *,
    coefficients_per_block: int,
    quantization_step: float,
    block_size: int = 32,
) -> bytes:
    original = np.asarray(source)
    decoded = np.asarray(proposal)
    if (
        original.dtype != np.uint8
        or decoded.dtype != np.uint8
        or original.shape != decoded.shape
        or original.ndim != 3
        or original.shape[2] != 3
        or original.shape[:2] != mask.shape
    ):
        raise ValueError("transform overlay requires matching uint8 RGB tiles and mask")
    if coefficients_per_block not in COEFFICIENT_COUNTS:
        raise ValueError("overlay coefficient count is not predeclared")
    if not 8 <= block_size <= 128:
        raise ValueError("overlay block size is outside the predeclared range")
    step_code = _step_code(quantization_step)
    height, width, _channels = original.shape
    body = bytearray()
    residual = original.astype(np.float64) - decoded.astype(np.float64)
    residual[~mask.pixels] = 0.0
    dct = _dct_matrix(block_size)
    coefficient_plane = block_size * block_size
    for y, x in _blocks(mask.pixels, block_size):
        block = np.zeros((block_size, block_size, 3), dtype=np.float64)
        block_height = min(block_size, height - y)
        block_width = min(block_size, width - x)
        block[:block_height, :block_width] = residual[
            y : y + block_height, x : x + block_width
        ]
        coefficients = np.stack(
            [dct @ block[:, :, channel] @ dct.T for channel in range(3)]
        ).reshape(-1)
        if coefficients_per_block == 0:
            for index in (0, coefficient_plane, coefficient_plane * 2):
                quantized = int(round(float(coefficients[index]) / quantization_step))
                if not -32768 <= quantized <= 32767:
                    raise ValueError("overlay coefficient exceeds canonical int16 range")
                body.extend(struct.pack(">h", quantized))
        else:
            indices = np.arange(coefficients.size)
            ranked = np.lexsort((indices, -np.abs(coefficients)))
            selected = np.sort(ranked[:coefficients_per_block]).tolist()
            for index in selected:
                quantized = int(round(float(coefficients[index]) / quantization_step))
                if not -32768 <= quantized <= 32767:
                    raise ValueError("overlay coefficient exceeds canonical int16 range")
                body.extend(COEFFICIENT.pack(index, quantized))
    mask_bytes = mask.encoded
    integrity = mask_bytes + body
    return HEADER.pack(
        MAGIC,
        height,
        width,
        block_size,
        coefficients_per_block,
        step_code,
        len(mask_bytes),
        len(body),
        hashlib.sha256(integrity).digest(),
    ) + integrity


def apply_transform_overlay(proposal: np.ndarray, payload: bytes) -> np.ndarray:
    if len(payload) < HEADER.size:
        raise ValueError("transform overlay is truncated")
    magic, height, width, block_size, count, step_code, mask_length, body_length, digest = HEADER.unpack_from(payload)
    integrity = payload[HEADER.size:]
    if (
        magic != MAGIC
        or not 8 <= block_size <= 128
        or count not in COEFFICIENT_COUNTS
        or step_code >= len(QUANTIZATION_STEPS)
        or len(integrity) != mask_length + body_length
        or hashlib.sha256(integrity).digest() != digest
    ):
        raise ValueError("transform-overlay header or integrity is invalid")
    decoded = np.asarray(proposal)
    if decoded.dtype != np.uint8 or decoded.shape != (height, width, 3):
        raise ValueError("transform overlay does not match decoded tile")
    mask = decode_repair_mask(integrity[:mask_length])
    if mask.shape != (height, width):
        raise ValueError("transform overlay mask dimensions are invalid")
    blocks = _blocks(mask.pixels, block_size)
    bytes_per_block = 6 if count == 0 else count * COEFFICIENT.size
    if body_length != len(blocks) * bytes_per_block:
        raise ValueError("transform-overlay coefficient length is invalid")
    body = integrity[mask_length:]
    repaired = decoded.astype(np.float64)
    offset = 0
    step = QUANTIZATION_STEPS[step_code]
    dct = _dct_matrix(block_size)
    coefficient_plane = block_size * block_size
    coefficient_total = coefficient_plane * 3
    for y, x in blocks:
        coefficients = np.zeros(coefficient_total, dtype=np.float64)
        if count == 0:
            for index in (0, coefficient_plane, coefficient_plane * 2):
                quantized = struct.unpack_from(">h", body, offset)[0]
                offset += 2
                coefficients[index] = quantized * step
        else:
            previous = -1
            for _entry in range(count):
                index, quantized = COEFFICIENT.unpack_from(body, offset)
                offset += COEFFICIENT.size
                if index <= previous or index >= coefficient_total:
                    raise ValueError("transform-overlay coefficients are noncanonical")
                coefficients[index] = quantized * step
                previous = index
        coefficients = coefficients.reshape(3, block_size, block_size)
        correction = np.stack(
            [dct.T @ coefficients[channel] @ dct for channel in range(3)],
            axis=2,
        )
        block_height = min(block_size, height - y)
        block_width = min(block_size, width - x)
        local_mask = mask.pixels[y : y + block_height, x : x + block_width]
        target = repaired[y : y + block_height, x : x + block_width]
        target[local_mask] += correction[:block_height, :block_width][local_mask]
    return np.clip(np.rint(repaired), 0, 255).astype(np.uint8)
