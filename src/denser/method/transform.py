from __future__ import annotations

import math

import numpy as np


BLOCK_SIZE = 8


def _dct_matrix() -> np.ndarray:
    matrix = np.empty((BLOCK_SIZE, BLOCK_SIZE), dtype=np.float64)
    for frequency in range(BLOCK_SIZE):
        scale = math.sqrt(1 / BLOCK_SIZE) if frequency == 0 else math.sqrt(2 / BLOCK_SIZE)
        for position in range(BLOCK_SIZE):
            matrix[frequency, position] = scale * math.cos(
                math.pi * (2 * position + 1) * frequency / (2 * BLOCK_SIZE)
            )
    return matrix


DCT8 = _dct_matrix()


def pad_rgb(values: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 3 or array.shape[2] != 3:
        raise ValueError("transform input must be RGB")
    height, width, _channels = array.shape
    padded_height = math.ceil(height / BLOCK_SIZE) * BLOCK_SIZE
    padded_width = math.ceil(width / BLOCK_SIZE) * BLOCK_SIZE
    padded = np.pad(
        array,
        ((0, padded_height - height), (0, padded_width - width), (0, 0)),
        mode="edge",
    )
    return padded, (height, width)


def forward_transform(values: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    padded, original_shape = pad_rgb(values)
    coefficients = np.empty_like(padded)
    for channel in range(3):
        for y in range(0, padded.shape[0], BLOCK_SIZE):
            for x in range(0, padded.shape[1], BLOCK_SIZE):
                block = padded[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE, channel]
                coefficients[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE, channel] = (
                    DCT8 @ block @ DCT8.T
                )
    return coefficients, original_shape


def inverse_transform(
    coefficients: np.ndarray, original_shape: tuple[int, int]
) -> np.ndarray:
    values = np.asarray(coefficients, dtype=np.float64)
    reconstructed = np.empty_like(values)
    for channel in range(3):
        for y in range(0, values.shape[0], BLOCK_SIZE):
            for x in range(0, values.shape[1], BLOCK_SIZE):
                block = values[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE, channel]
                reconstructed[y : y + BLOCK_SIZE, x : x + BLOCK_SIZE, channel] = (
                    DCT8.T @ block @ DCT8
                )
    height, width = original_shape
    return np.clip(np.rint(reconstructed[:height, :width]), 0, 255).astype(np.uint8)
