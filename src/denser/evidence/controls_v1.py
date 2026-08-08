from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from PIL import Image, ImageFilter

from denser.evidence.architecture import compute_acceptance_evidence
from denser.evidence.controls import ControlPair
from denser.evidence.nuclei import connected_components
from denser.evidence.types import AcceptanceContract, PhysicalGrid


BENIGN_CONTROLS = (
    "exposure_plus_1",
    "channel_drift_1",
    "sensor_noise_1",
)

HARMFUL_CONTROLS: Mapping[str, str] = {
    "nuclear_edge_blur": "nuclear_objects",
    "chromatin_removal": "nuclear_objects",
    "small_object_deletion": "rare_event_sentinels",
    "boundary_shift": "nuclear_objects",
    "local_color_collapse": "visual",
}


def _validate(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("HE-V1 controls require canonical uint8 RGB pixels")
    return pixels


def _sensor_noise(pixels: np.ndarray, seed: int) -> np.ndarray:
    generator = np.random.default_rng(seed)
    noise = generator.integers(-1, 2, size=pixels.shape, dtype=np.int16)
    return np.clip(pixels.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _small_object_deletion(pixels: np.ndarray) -> np.ndarray:
    altered = pixels.copy()
    intensity = pixels.astype(np.float64).mean(axis=2)
    background = np.median(pixels.reshape(-1, 3), axis=0).astype(np.uint8)
    for component in connected_components(intensity < 80):
        if 1 <= len(component) <= 16:
            for y, x in component:
                altered[y, x] = background
    return altered


def _boundary_shift(pixels: np.ndarray) -> np.ndarray:
    altered = pixels.copy()
    intensity = pixels.astype(np.float64).mean(axis=2)
    mask = intensity < 140
    shifted = np.roll(mask, 4, axis=1)
    shifted[:, :4] = False
    tissue = pixels[(intensity >= 140) & (intensity < 240)]
    fill = (
        np.median(tissue, axis=0).astype(np.uint8)
        if tissue.size
        else np.array([210, 145, 182], dtype=np.uint8)
    )
    dark = pixels[mask]
    pigment = (
        np.median(dark, axis=0).astype(np.uint8)
        if dark.size
        else np.array([70, 35, 95], dtype=np.uint8)
    )
    altered[mask] = fill
    altered[shifted] = pigment
    return altered


def _local_color_collapse(pixels: np.ndarray) -> np.ndarray:
    altered = pixels.copy()
    height, width, _channels = pixels.shape
    y0, y1 = height // 4, max(height // 4 + 1, 3 * height // 4)
    x0, x1 = width // 4, max(width // 4 + 1, 3 * width // 4)
    patch = altered[y0:y1, x0:x1]
    luminance = np.rint(patch.astype(np.float64).mean(axis=2)).astype(np.uint8)
    altered[y0:y1, x0:x1] = np.repeat(luminance[:, :, None], 3, axis=2)
    return altered


def transform_control(rgb: np.ndarray, control_name: str, *, seed: int) -> np.ndarray:
    pixels = _validate(rgb)
    if control_name == "exposure_plus_1":
        return np.clip(pixels.astype(np.int16) + 1, 0, 255).astype(np.uint8)
    if control_name == "channel_drift_1":
        altered = pixels.astype(np.int16)
        altered[:, :, 0] += 1
        altered[:, :, 2] -= 1
        return np.clip(altered, 0, 255).astype(np.uint8)
    if control_name == "sensor_noise_1":
        return _sensor_noise(pixels, seed)
    if control_name == "nuclear_edge_blur":
        return np.asarray(
            Image.fromarray(pixels, mode="RGB").filter(ImageFilter.GaussianBlur(radius=3.0)),
            dtype=np.uint8,
        )
    if control_name == "chromatin_removal":
        altered = pixels.copy()
        mask = pixels.astype(np.float64).mean(axis=2) < 140
        altered[mask] = np.maximum(altered[mask], np.array([185, 145, 190], dtype=np.uint8))
        return altered
    if control_name == "small_object_deletion":
        return _small_object_deletion(pixels)
    if control_name == "boundary_shift":
        return _boundary_shift(pixels)
    if control_name == "local_color_collapse":
        return _local_color_collapse(pixels)
    raise ValueError(f"unknown HE-V1 control: {control_name}")


def build_control_pair(
    source: np.ndarray,
    *,
    tile_id: str,
    control_name: str,
    grid: PhysicalGrid,
    seed: int,
) -> ControlPair:
    altered = transform_control(source, control_name, seed=seed)
    contract = AcceptanceContract()
    reference = dict(compute_acceptance_evidence(source, grid, contract).groups)
    candidate = dict(compute_acceptance_evidence(altered, grid, contract).groups)
    deltas = tuple(
        (
            name,
            tuple(
                round(abs(float(left) - float(right)), 12)
                for left, right in zip(values, candidate[name], strict=True)
            ),
        )
        for name, values in reference.items()
    )
    kind = "benign" if control_name in BENIGN_CONTROLS else "harmful"
    expected_group = HARMFUL_CONTROLS.get(control_name)
    return ControlPair(
        f"{tile_id}:{control_name}",
        tile_id,
        kind,
        expected_group,
        deltas,
    )


def build_control_cohort(
    tiles: Sequence[tuple[np.ndarray, str]],
    grid: PhysicalGrid,
    *,
    seed: int,
) -> tuple[tuple[ControlPair, ...], tuple[ControlPair, ...]]:
    challenge_count = len(HARMFUL_CONTROLS)
    if len(tiles) < challenge_count + 2:
        raise ValueError("control cohort requires two fit tiles plus disjoint harmful challenges")
    fit_tiles = tiles[:-challenge_count]
    challenge_tiles = tiles[-challenge_count:]
    benign = tuple(
        build_control_pair(
            pixels,
            tile_id=tile_id,
            control_name=BENIGN_CONTROLS[index % len(BENIGN_CONTROLS)],
            grid=grid,
            seed=seed + index,
        )
        for index, (pixels, tile_id) in enumerate(fit_tiles)
    )
    harmful = tuple(
        build_control_pair(
            pixels,
            tile_id=tile_id,
            control_name=control_name,
            grid=grid,
            seed=seed + len(fit_tiles) + index,
        )
        for index, ((pixels, tile_id), control_name) in enumerate(
            zip(challenge_tiles, HARMFUL_CONTROLS, strict=True)
        )
    )
    return benign, harmful
