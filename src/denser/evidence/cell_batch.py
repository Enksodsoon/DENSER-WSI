from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from denser.evidence.stain import hematoxylin_concentration, sentinel_mask
from denser.evidence.types import AcceptanceContract, PhysicalGrid


@dataclass(frozen=True, slots=True)
class CellAcceptanceBatch:
    bounds: tuple[tuple[int, int, int, int], ...]
    groups: tuple[tuple[str, np.ndarray], ...]


def _cells(values: np.ndarray, size: int) -> np.ndarray:
    height, width = values.shape[:2]
    trailing = values.shape[2:]
    return values.reshape(
        height // size, size, width // size, size, *trailing
    ).transpose(0, 2, 1, 3, *range(4, 4 + len(trailing)))


def _component_groups(mask: np.ndarray, size: int) -> dict[int, list[tuple[int, int, int, bool]]]:
    height, width = mask.shape
    rows, columns = height // size, width // size
    cell_masks = _cells(mask, size)
    separated = np.zeros((rows, size + 1, columns, size + 1), dtype=np.bool_)
    separated[:, :size, :, :size] = cell_masks.transpose(0, 2, 1, 3)
    mosaic = separated.transpose(0, 1, 2, 3).reshape(
        rows * (size + 1), columns * (size + 1)
    )
    structure = np.array(((0, 1, 0), (1, 1, 1), (0, 1, 0)), dtype=np.uint8)
    labels, count = ndimage.label(mosaic, structure=structure)
    if not count:
        return {}
    y_values, x_values = np.nonzero(labels)
    component_labels = labels[y_values, x_values]
    local_y = y_values % (size + 1)
    local_x = x_values % (size + 1)
    cell_ids = (y_values // (size + 1)) * columns + x_values // (size + 1)
    sizes = np.bincount(component_labels, minlength=count + 1)
    sums_y = np.bincount(component_labels, weights=local_y, minlength=count + 1)
    sums_x = np.bincount(component_labels, weights=local_x, minlength=count + 1)
    component_cells = np.full(count + 1, rows * columns, dtype=np.int64)
    np.minimum.at(component_cells, component_labels, cell_ids)
    touches = np.zeros(count + 1, dtype=np.bool_)
    np.logical_or.at(
        touches,
        component_labels,
        (local_y == 0)
        | (local_y == size - 1)
        | (local_x == 0)
        | (local_x == size - 1),
    )
    grouped: dict[int, list[tuple[int, int, int, bool]]] = defaultdict(list)
    for label in range(1, count + 1):
        grouped[int(component_cells[label])].append(
            (
                int(sizes[label]),
                int(sums_y[label]),
                int(sums_x[label]),
                bool(touches[label]),
            )
        )
    return dict(grouped)


def _spatial_means(values: np.ndarray) -> np.ndarray:
    rows, columns, size, _ = values.shape
    return values.reshape(rows, columns, 4, size // 4, 4, size // 4).mean(
        axis=(3, 5)
    ).reshape(rows * columns, 16)


def compute_cell_acceptance_batch(
    rgb: np.ndarray,
    grid: PhysicalGrid,
    cell_size: int,
) -> CellAcceptanceBatch | None:
    pixels = np.asarray(rgb)
    if (
        pixels.dtype != np.uint8
        or pixels.ndim != 3
        or pixels.shape[2] != 3
        or cell_size < 4
        or cell_size % 4
        or pixels.shape[0] % cell_size
        or pixels.shape[1] % cell_size
    ):
        return None
    height, width, _ = pixels.shape
    rows, columns = height // cell_size, width // cell_size
    cell_count = rows * columns
    area = cell_size * cell_size
    cell_pixels = _cells(pixels, cell_size)
    flat_pixels = cell_pixels.reshape(cell_count, area, 3)
    normalized = flat_pixels.astype(np.float64) / 255.0
    hematoxylin = hematoxylin_concentration(pixels)
    cell_h = _cells(hematoxylin, cell_size)
    flat_h = cell_h.reshape(cell_count, area)

    pixel_area_um2 = grid.mpp_x * grid.mpp_y
    nuclear_min = max(1, int(np.ceil(0.25 / pixel_area_um2)))
    nuclear_max = max(nuclear_min, int(np.floor(128.0 / pixel_area_um2)))
    nuclear_components = _component_groups(hematoxylin > 0.55, cell_size)
    sentinel = sentinel_mask(pixels, hematoxylin=hematoxylin)
    sentinel_min = max(1, int(np.ceil(0.05 / pixel_area_um2)))
    sentinel_max = max(sentinel_min, int(np.floor(4.0 / pixel_area_um2)))
    sentinel_components = _component_groups(sentinel, cell_size)
    bright = np.all(pixels > 245, axis=2)
    lumen_min = max(1, int(np.ceil(0.25 / pixel_area_um2)))
    lumen_components = _component_groups(bright, cell_size)

    h_mean = flat_h.mean(axis=1)
    h_q95 = np.quantile(flat_h, 0.95, axis=1)
    h_q99 = np.quantile(flat_h, 0.99, axis=1)
    boundary = []
    for scale_um in (0.25, 0.50, 1.00):
        offset = max(1, int(round(scale_um / grid.mean_mpp)))
        if cell_size <= offset:
            boundary.append(np.zeros(cell_count))
        else:
            horizontal = np.abs(cell_h[:, :, :, offset:] - cell_h[:, :, :, :-offset]).mean(
                axis=(2, 3)
            )
            vertical = np.abs(cell_h[:, :, offset:, :] - cell_h[:, :, :-offset, :]).mean(
                axis=(2, 3)
            )
            boundary.append(((horizontal + vertical) / 2).reshape(cell_count))
    if cell_size < 3:
        chromatin_mean = chromatin_q95 = np.zeros(cell_count)
    else:
        laplacian = np.abs(
            -4.0 * cell_h[:, :, 1:-1, 1:-1]
            + cell_h[:, :, :-2, 1:-1]
            + cell_h[:, :, 2:, 1:-1]
            + cell_h[:, :, 1:-1, :-2]
            + cell_h[:, :, 1:-1, 2:]
        ) / (grid.mean_mpp**2)
        flat_laplacian = laplacian.reshape(cell_count, -1)
        chromatin_mean = flat_laplacian.mean(axis=1)
        chromatin_q95 = np.quantile(flat_laplacian, 0.95, axis=1)
    h_spatial = _spatial_means(cell_h)

    histograms = []
    cell_ids = np.repeat(np.arange(cell_count), area)
    for channel in range(3):
        bins = flat_pixels[:, :, channel].reshape(-1) // 16
        histograms.append(
            np.bincount(cell_ids * 16 + bins, minlength=cell_count * 16).reshape(
                cell_count, 16
            )
            / area
        )
    luminance = flat_pixels.astype(np.float64).mean(axis=2)
    tissue_fraction = (luminance < 240).mean(axis=1)
    channel_mean = normalized.mean(axis=1)
    channel_std = normalized.std(axis=1)
    red_green = normalized[:, :, 0] - normalized[:, :, 1]
    blue_green = normalized[:, :, 2] - normalized[:, :, 1]
    red_green_abs_mean = np.abs(red_green).mean(axis=1)
    red_green_std = red_green.std(axis=1)
    blue_green_abs_mean = np.abs(blue_green).mean(axis=1)
    blue_green_std = blue_green.std(axis=1)
    centered = normalized - channel_mean[:, None, :]
    covariance = np.einsum("npi,npj->nij", centered, centered) / max(area - 1, 1)
    covariance_std = np.sqrt(
        np.maximum(np.diagonal(covariance, axis1=1, axis2=2), 1e-12)
    )
    correlation = covariance / (
        covariance_std[:, :, None] * covariance_std[:, None, :]
    )
    covariance_determinant = np.linalg.det(covariance)
    red_spatial = _spatial_means(np.abs(red_green).reshape(rows, columns, cell_size, cell_size))
    blue_spatial = _spatial_means(
        np.abs(blue_green).reshape(rows, columns, cell_size, cell_size)
    )

    bounds_rows: list[tuple[int, int, int, int]] = []
    group_rows: dict[str, list[tuple[float, ...]]] = {
        "nuclear_objects": [],
        "architecture": [],
        "rare_event_sentinels": [],
        "visual": [],
    }
    for index in range(cell_count):
        nuclear = [
            value
            for value in nuclear_components.get(index, ())
            if nuclear_min <= value[0] <= nuclear_max
        ]
        nuclear_area = sum(value[0] for value in nuclear)
        nuclear_y = (
            sum(value[1] / value[0] for value in nuclear) / len(nuclear)
            if nuclear
            else 0.0
        )
        nuclear_x = (
            sum(value[2] / value[0] for value in nuclear) / len(nuclear)
            if nuclear
            else 0.0
        )
        nuclear_values = (
            len(nuclear) * 1_000_000.0 / (area * pixel_area_um2),
            nuclear_area / area,
            nuclear_y / max(cell_size - 1, 1),
            nuclear_x / max(cell_size - 1, 1),
            h_mean[index],
            h_q95[index],
            h_q99[index],
            *(values[index] for values in boundary),
            chromatin_mean[index],
            chromatin_q95[index],
            *h_spatial[index],
        )
        sentinel_values_raw = [
            value
            for value in sentinel_components.get(index, ())
            if sentinel_min <= value[0] <= sentinel_max
        ]
        sentinel_total = sum(value[0] for value in sentinel_values_raw)
        sentinel_values = (
            len(sentinel_values_raw) * 1_000_000.0 / (area * pixel_area_um2),
            sentinel_total / area,
            (sum(value[1] for value in sentinel_values_raw) / sentinel_total)
            / max(cell_size - 1, 1)
            if sentinel_total
            else 0.0,
            (sum(value[2] for value in sentinel_values_raw) / sentinel_total)
            / max(cell_size - 1, 1)
            if sentinel_total
            else 0.0,
        )
        enclosed = [
            value
            for value in lumen_components.get(index, ())
            if not value[3] and value[0] >= lumen_min
        ]
        architecture_values = (
            float(len(enclosed)),
            sum(value[0] for value in enclosed) / area,
            tissue_fraction[index],
        )
        visual_values = (
            *histograms[0][index],
            *histograms[1][index],
            *histograms[2][index],
            float(luminance[index].mean() / 255),
            float(luminance[index].std() / 255),
            channel_mean[index, 0],
            channel_std[index, 0],
            channel_mean[index, 1],
            channel_std[index, 1],
            channel_mean[index, 2],
            channel_std[index, 2],
            red_green_abs_mean[index],
            red_green_std[index],
            blue_green_abs_mean[index],
            blue_green_std[index],
            correlation[index, 0, 1],
            correlation[index, 0, 2],
            correlation[index, 1, 2],
            covariance_determinant[index],
            *np.column_stack((red_spatial[index], blue_spatial[index])).ravel(),
        )
        cell_y, cell_x = divmod(index, columns)
        bounds_rows.append(
            (cell_x * cell_size, cell_y * cell_size, cell_size, cell_size)
        )
        group_rows["nuclear_objects"].append(nuclear_values)
        group_rows["architecture"].append(architecture_values)
        group_rows["rare_event_sentinels"].append(sentinel_values)
        group_rows["visual"].append(visual_values)
    return CellAcceptanceBatch(
        tuple(bounds_rows),
        tuple(
            (name, np.round(np.asarray(group_rows[name], dtype=np.float64), 12))
            for name in (
                "nuclear_objects",
                "architecture",
                "rare_event_sentinels",
                "visual",
            )
        ),
    )


def compute_cell_acceptance_groups(
    rgb: np.ndarray,
    grid: PhysicalGrid,
    cell_size: int,
) -> dict[tuple[int, int, int, int], tuple[tuple[str, tuple[float, ...]], ...]] | None:
    batch = compute_cell_acceptance_batch(rgb, grid, cell_size)
    if batch is None:
        return None
    return {
        bounds: tuple(
            (name, tuple(float(value) for value in values[index]))
            for name, values in batch.groups
        )
        for index, bounds in enumerate(batch.bounds)
    }


def compare_cell_acceptance_batches(
    reference: CellAcceptanceBatch,
    candidate: CellAcceptanceBatch,
    contract: AcceptanceContract,
) -> dict[tuple[int, int, int, int], tuple[str, ...]]:
    if reference.bounds != candidate.bounds:
        raise ValueError("cell evidence batches have different bounds")
    reference_groups = dict(reference.groups)
    candidate_groups = dict(candidate.groups)
    if reference_groups.keys() != candidate_groups.keys():
        raise ValueError("cell evidence batches have different groups")
    calibrated = dict(contract.absolute_group_bounds)
    tolerances = {
        "nuclear_objects": contract.nuclear_relative_tolerance,
        "architecture": contract.architecture_relative_tolerance,
        "rare_event_sentinels": contract.sentinel_relative_tolerance,
        "visual": contract.visual_relative_tolerance,
    }
    failed: list[list[str]] = [[] for _bounds in reference.bounds]
    for name, first in reference.groups:
        second = candidate_groups[name]
        if first.shape != second.shape:
            raise ValueError("cell evidence group shapes differ")
        if calibrated:
            bounds = np.asarray(calibrated[name], dtype=np.float64)
            if bounds.shape != first.shape[1:]:
                raise ValueError("calibrated bound shape does not match evidence group")
            distance = np.max(np.abs(first - second) / bounds, axis=1)
            threshold = 1.0
        else:
            scale = np.maximum(np.abs(first), 1e-6)
            distance = np.max(np.abs(first - second) / scale, axis=1)
            threshold = tolerances[name]
        for index in np.flatnonzero(distance > threshold):
            failed[int(index)].append(name)
    return {
        bounds: tuple(failed[index])
        for index, bounds in enumerate(reference.bounds)
    }
