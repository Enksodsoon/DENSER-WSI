from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from PIL import Image, ImageFilter

from denser.evidence.architecture import (
    compute_acceptance_evidence,
    compute_acceptance_groups,
)
from denser.evidence.controls import ControlPair
from denser.evidence.nuclei import connected_components, nuclear_features
from denser.evidence.sentinels import sentinel_features
from denser.evidence.stain import hematoxylin_concentration, sentinel_mask
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

_FROZEN_BENIGN_ROWS = (
    {"name": "exposure_plus_1", "digital_levels": 1},
    {"name": "channel_drift_1", "digital_levels": 1},
    {"name": "sensor_noise_1", "digital_levels": 1},
)
_FROZEN_HARMFUL_ROWS = (
    {"name": "nuclear_edge_blur", "expected_group": "nuclear_objects", "radius_um": 2.0},
    {"name": "chromatin_removal", "expected_group": "nuclear_objects", "hematoxylin_threshold": 0.55},
    {"name": "small_object_deletion", "expected_group": "rare_event_sentinels", "maximum_area_um2": 4.0},
    {"name": "boundary_shift", "expected_group": "nuclear_objects", "outward_displacement_um": 1.0},
    {"name": "local_color_collapse", "expected_group": "visual", "retained_margin_fraction": 0.03125},
)


def verify_control_configuration(document: Mapping[str, object]) -> None:
    """Bind real calibration to the reviewed HE-V1 control specification."""
    expected_scalars = {
        "version": "HE-V1-calibration-3",
        "alpha": 0.05,
        "tile_size_px": 512,
        "spatial_summary_grid": [4, 4],
        "threshold_basis": "tile_familywise_max",
    }
    if any(document.get(name) != value for name, value in expected_scalars.items()):
        raise ValueError("HE-V1 control configuration does not match the frozen specification")
    if tuple(document.get("benign_controls", ())) != _FROZEN_BENIGN_ROWS:
        raise ValueError("HE-V1 benign controls do not match the frozen specification")
    if tuple(document.get("harmful_controls", ())) != _FROZEN_HARMFUL_ROWS:
        raise ValueError("HE-V1 harmful controls do not match the frozen specification")


def _validate(rgb: np.ndarray) -> np.ndarray:
    pixels = np.asarray(rgb)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("HE-V1 controls require canonical uint8 RGB pixels")
    return pixels


def _sensor_noise(pixels: np.ndarray, seed: int) -> np.ndarray:
    generator = np.random.default_rng(seed)
    noise = generator.integers(-1, 2, size=pixels.shape, dtype=np.int16)
    return np.clip(pixels.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _small_object_deletion(pixels: np.ndarray, grid: PhysicalGrid) -> np.ndarray:
    altered = pixels.copy()
    background = np.median(pixels.reshape(-1, 3), axis=0).astype(np.uint8)
    maximum_pixels = max(
        1, int(np.floor(4.0 / (grid.mpp_x * grid.mpp_y)))
    )
    for component in connected_components(sentinel_mask(pixels)):
        if 1 <= len(component) <= maximum_pixels:
            for y, x in component:
                altered[y, x] = background
    return altered


def _boundary_shift(pixels: np.ndarray, radius: int) -> np.ndarray:
    altered = pixels.copy()
    intensity = pixels.astype(np.float64).mean(axis=2)
    mask = intensity < 140
    displaced = mask.copy()
    for offset_y in range(-radius, radius + 1):
        for offset_x in range(-radius, radius + 1):
            if offset_x * offset_x + offset_y * offset_y <= radius * radius:
                shifted = np.roll(mask, (offset_y, offset_x), axis=(0, 1))
                if offset_y < 0:
                    shifted[offset_y:] = False
                elif offset_y > 0:
                    shifted[:offset_y] = False
                if offset_x < 0:
                    shifted[:, offset_x:] = False
                elif offset_x > 0:
                    shifted[:, :offset_x] = False
                displaced |= shifted
    dark = pixels[mask]
    pigment = (
        np.median(dark, axis=0).astype(np.uint8)
        if dark.size
        else np.array([70, 35, 95], dtype=np.uint8)
    )
    altered[displaced & ~mask] = pigment
    return altered


def _local_color_collapse(pixels: np.ndarray) -> np.ndarray:
    altered = pixels.copy()
    height, width, _channels = pixels.shape
    margin_y = max(1, height // 32)
    margin_x = max(1, width // 32)
    y0, y1 = margin_y, max(margin_y + 1, height - margin_y)
    x0, x1 = margin_x, max(margin_x + 1, width - margin_x)
    patch = altered[y0:y1, x0:x1]
    luminance = np.rint(patch.astype(np.float64).mean(axis=2)).astype(np.uint8)
    altered[y0:y1, x0:x1] = np.repeat(luminance[:, :, None], 3, axis=2)
    return altered


def transform_control(
    rgb: np.ndarray,
    control_name: str,
    *,
    seed: int,
    grid: PhysicalGrid | None = None,
) -> np.ndarray:
    pixels = _validate(rgb)
    selected_grid = grid or PhysicalGrid(0.25, 0.25)
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
        radius = max(1.0, 2.0 / selected_grid.mean_mpp)
        return np.asarray(
            Image.fromarray(pixels, mode="RGB").filter(ImageFilter.GaussianBlur(radius=radius)),
            dtype=np.uint8,
        )
    if control_name == "chromatin_removal":
        altered = pixels.copy()
        mask = hematoxylin_concentration(pixels) > 0.55
        altered[mask] = np.array([220, 170, 200], dtype=np.uint8)
        return altered
    if control_name == "small_object_deletion":
        return _small_object_deletion(pixels, selected_grid)
    if control_name == "boundary_shift":
        radius = max(1, int(round(1.0 / selected_grid.mean_mpp)))
        return _boundary_shift(pixels, radius)
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
    altered = transform_control(source, control_name, seed=seed, grid=grid)
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
    cell_size = max(1, round(8.0 / grid.mean_mpp))
    cell_values: dict[str, list[tuple[float, ...]]] = {
        name: [] for name in reference
    }
    height, width, _channels = source.shape
    for y in range(0, height, cell_size):
        for x in range(0, width, cell_size):
            reference_cell = dict(
                compute_acceptance_groups(
                    source[y : y + cell_size, x : x + cell_size], grid
                )
            )
            candidate_cell = dict(
                compute_acceptance_groups(
                    altered[y : y + cell_size, x : x + cell_size], grid
                )
            )
            for name in reference:
                cell_values[name].append(
                    tuple(
                        round(abs(float(left) - float(right)), 12)
                        for left, right in zip(
                            reference_cell[name], candidate_cell[name], strict=True
                        )
                    )
                )
    kind = "benign" if control_name in BENIGN_CONTROLS else "harmful"
    expected_group = HARMFUL_CONTROLS.get(control_name)
    return ControlPair(
        f"{tile_id}:{control_name}",
        tile_id,
        kind,
        expected_group,
        deltas,
        tuple((name, tuple(cell_values[name])) for name in reference),
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


def control_applicability(
    rgb: np.ndarray,
    control_name: str,
    grid: PhysicalGrid | None = None,
) -> float:
    pixels = _validate(rgb)
    selected_grid = grid or PhysicalGrid(0.25, 0.25)
    if control_name == "small_object_deletion":
        values = sentinel_features(pixels, selected_grid)
        return float(values[0] + values[1] * 1_000_000.0)
    if control_name == "local_color_collapse":
        values = pixels.astype(np.float64)
        chroma = np.stack(
            (values[:, :, 0] - values[:, :, 1], values[:, :, 2] - values[:, :, 1]),
            axis=2,
        )
        return float(chroma.std())
    values = nuclear_features(pixels, selected_grid)
    if control_name == "nuclear_edge_blur":
        return float(sum(values[7:12]))
    if control_name == "chromatin_removal":
        return float(values[6] + sum(values[10:12]))
    if control_name == "boundary_shift":
        return float(values[1] * (values[0] + 1.0))
    raise ValueError(f"unknown harmful control: {control_name}")


def build_balanced_control_cohort(
    slides: Sequence[Sequence[tuple[np.ndarray, str, PhysicalGrid]]],
    *,
    seed: int,
) -> tuple[tuple[ControlPair, ...], tuple[ControlPair, ...]]:
    mechanisms = tuple(HARMFUL_CONTROLS)
    if len(slides) < len(mechanisms):
        raise ValueError("balanced controls require one development slide per harmful mechanism")
    remaining = [list(rows) for rows in slides]
    harmful: list[ControlPair] = []
    for slide_index, control_name in enumerate(mechanisms):
        if not remaining[slide_index]:
            raise ValueError("development slide has no control tiles")
        chosen_index = max(
            range(len(remaining[slide_index])),
            key=lambda index: (
                control_applicability(
                    remaining[slide_index][index][0],
                    control_name,
                    remaining[slide_index][index][2],
                ),
                remaining[slide_index][index][1],
            ),
        )
        chosen = remaining[slide_index].pop(chosen_index)
        pixels, tile_id, grid = chosen
        harmful.append(
            build_control_pair(
                pixels,
                tile_id=tile_id,
                control_name=control_name,
                grid=grid,
                seed=seed + slide_index,
            )
        )
    fit_rows = [row for slide_rows in remaining for row in slide_rows]
    if len(fit_rows) < 2:
        raise ValueError("balanced controls require at least two benign fit tiles")
    benign = tuple(
        build_control_pair(
            pixels,
            tile_id=tile_id,
            control_name=BENIGN_CONTROLS[index % len(BENIGN_CONTROLS)],
            grid=grid,
            seed=seed + len(mechanisms) + index,
        )
        for index, (pixels, tile_id, grid) in enumerate(fit_rows)
    )
    return benign, tuple(harmful)
