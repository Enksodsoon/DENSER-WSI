from __future__ import annotations

import numpy as np


def visual_features(rgb: np.ndarray) -> tuple[float, ...]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    features: list[float] = []
    for channel in range(3):
        histogram = np.bincount(
            (pixels[:, :, channel].ravel() // 16), minlength=16
        )
        features.extend((histogram / pixels[:, :, channel].size).tolist())
    luminance = pixels.astype(np.float64).mean(axis=2)
    features.extend((float(luminance.mean() / 255), float(luminance.std() / 255)))
    normalized = pixels.astype(np.float64) / 255.0
    for channel in range(3):
        features.extend(
            (
                float(normalized[:, :, channel].mean()),
                float(normalized[:, :, channel].std()),
            )
        )
    red_green = normalized[:, :, 0] - normalized[:, :, 1]
    blue_green = normalized[:, :, 2] - normalized[:, :, 1]
    features.extend(
        (
            float(np.mean(np.abs(red_green))),
            float(np.std(red_green)),
            float(np.mean(np.abs(blue_green))),
            float(np.std(blue_green)),
        )
    )
    flattened = normalized.reshape(-1, 3)
    if len(flattened) > 1:
        centered = flattened - flattened.mean(axis=0)
        covariance = centered.T @ centered / (len(flattened) - 1)
    else:
        covariance = np.zeros((3, 3))
    channel_std = np.sqrt(np.maximum(np.diag(covariance), 1e-12))
    correlation = covariance / np.outer(channel_std, channel_std)
    features.extend(
        (
            float(correlation[0, 1]),
            float(correlation[0, 2]),
            float(correlation[1, 2]),
            float(np.linalg.det(covariance)),
        )
    )
    height, width = luminance.shape
    if height % 4 == 0 and width % 4 == 0:
        red_spatial = np.abs(red_green).reshape(4, height // 4, 4, width // 4).mean(
            axis=(1, 3)
        )
        blue_spatial = np.abs(blue_green).reshape(
            4, height // 4, 4, width // 4
        ).mean(axis=(1, 3))
        for red_value, blue_value in zip(
            red_spatial.ravel(), blue_spatial.ravel(), strict=True
        ):
            features.extend((float(red_value), float(blue_value)))
    else:
        for y_indices in np.array_split(np.arange(height), 4):
            for x_indices in np.array_split(np.arange(width), 4):
                red_green_block = red_green[np.ix_(y_indices, x_indices)]
                blue_green_block = blue_green[np.ix_(y_indices, x_indices)]
                features.extend(
                    (
                        float(np.mean(np.abs(red_green_block)))
                        if red_green_block.size
                        else 0.0,
                        float(np.mean(np.abs(blue_green_block)))
                        if blue_green_block.size
                        else 0.0,
                    )
                )
    return tuple(features)
