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


def _cells(values: np.ndarray, cell_height: int, cell_width: int) -> np.ndarray:
    height, width = values.shape[:2]
    trailing = values.shape[2:]
    return values.reshape(
        height // cell_height,
        cell_height,
        width // cell_width,
        cell_width,
        *trailing,
    ).transpose(0, 2, 1, 3, *range(4, 4 + len(trailing)))


def _component_groups(
    mask: np.ndarray, cell_height: int, cell_width: int
) -> dict[int, list[tuple[int, int, int, bool]]]:
    height, width = mask.shape
    rows, columns = height // cell_height, width // cell_width
    cell_masks = _cells(mask, cell_height, cell_width)
    separated = np.zeros(
        (rows, cell_height + 1, columns, cell_width + 1), dtype=np.bool_
    )
    separated[:, :cell_height, :, :cell_width] = cell_masks.transpose(0, 2, 1, 3)
    mosaic = separated.transpose(0, 1, 2, 3).reshape(
        rows * (cell_height + 1), columns * (cell_width + 1)
    )
    structure = np.array(((0, 1, 0), (1, 1, 1), (0, 1, 0)), dtype=np.uint8)
    labels, count = ndimage.label(mosaic, structure=structure)
    if not count:
        return {}
    y_values, x_values = np.nonzero(labels)
    component_labels = labels[y_values, x_values]
    local_y = y_values % (cell_height + 1)
    local_x = x_values % (cell_width + 1)
    cell_ids = (y_values // (cell_height + 1)) * columns + x_values // (
        cell_width + 1
    )
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
        | (local_y == cell_height - 1)
        | (local_x == 0)
        | (local_x == cell_width - 1),
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
    rows, columns, height, width = values.shape
    if height % 4 == 0 and width % 4 == 0:
        return values.reshape(
            rows, columns, 4, height // 4, 4, width // 4
        ).mean(axis=(3, 5)).reshape(rows * columns, 16)
    height_quotient, height_remainder = divmod(height, 4)
    width_quotient, width_remainder = divmod(width, 4)
    height_edges = np.cumsum(
        (
            0,
            *(
                height_quotient + (1 if index < height_remainder else 0)
                for index in range(4)
            ),
        )
    )
    width_edges = np.cumsum(
        (
            0,
            *(
                width_quotient + (1 if index < width_remainder else 0)
                for index in range(4)
            ),
        )
    )
    return np.stack(
        [
            values[
                :,
                :,
                height_edges[y] : height_edges[y + 1],
                width_edges[x] : width_edges[x + 1],
            ].mean(axis=(2, 3))
            for y in range(4)
            for x in range(4)
        ],
        axis=2,
    ).reshape(rows * columns, 16)


def _compute_rectangular_cell_acceptance_batch(
    rgb: np.ndarray,
    grid: PhysicalGrid,
    cell_height: int,
    cell_width: int,
) -> CellAcceptanceBatch | None:
    pixels = np.asarray(rgb)
    if (
        pixels.dtype != np.uint8
        or pixels.ndim != 3
        or pixels.shape[2] != 3
        or min(cell_height, cell_width) < 4
        or pixels.shape[0] % cell_height
        or pixels.shape[1] % cell_width
    ):
        return None
    height, width, _ = pixels.shape
    rows, columns = height // cell_height, width // cell_width
    cell_count = rows * columns
    area = cell_height * cell_width
    cell_pixels = _cells(pixels, cell_height, cell_width)
    flat_pixels = cell_pixels.reshape(cell_count, area, 3)
    normalized = flat_pixels.astype(np.float64) / 255.0
    hematoxylin = hematoxylin_concentration(pixels)
    cell_h = _cells(hematoxylin, cell_height, cell_width)
    flat_h = cell_h.reshape(cell_count, area)

    pixel_area_um2 = grid.mpp_x * grid.mpp_y
    nuclear_min = max(1, int(np.ceil(0.25 / pixel_area_um2)))
    nuclear_max = max(nuclear_min, int(np.floor(128.0 / pixel_area_um2)))
    nuclear_components = _component_groups(
        hematoxylin > 0.55, cell_height, cell_width
    )
    sentinel = sentinel_mask(pixels, hematoxylin=hematoxylin)
    sentinel_min = max(1, int(np.ceil(0.05 / pixel_area_um2)))
    sentinel_max = max(sentinel_min, int(np.floor(4.0 / pixel_area_um2)))
    sentinel_components = _component_groups(sentinel, cell_height, cell_width)
    bright = np.all(pixels > 245, axis=2)
    lumen_min = max(1, int(np.ceil(0.25 / pixel_area_um2)))
    lumen_components = _component_groups(bright, cell_height, cell_width)

    h_mean = flat_h.mean(axis=1)
    h_q95 = np.quantile(flat_h, 0.95, axis=1)
    h_q99 = np.quantile(flat_h, 0.99, axis=1)
    boundary = []
    for scale_um in (0.25, 0.50, 1.00):
        offset = max(1, int(round(scale_um / grid.mean_mpp)))
        if min(cell_height, cell_width) <= offset:
            boundary.append(np.zeros(cell_count))
        else:
            horizontal = np.abs(cell_h[:, :, :, offset:] - cell_h[:, :, :, :-offset]).mean(
                axis=(2, 3)
            )
            vertical = (
                np.abs(cell_h[:, :, offset:, :] - cell_h[:, :, :-offset, :]).mean(
                    axis=(2, 3)
                )
                if cell_height > offset
                else np.zeros((rows, columns))
            )
            boundary.append(((horizontal + vertical) / 2).reshape(cell_count))
    if min(cell_height, cell_width) < 3:
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
    red_spatial = _spatial_means(
        np.abs(red_green).reshape(rows, columns, cell_height, cell_width)
    )
    blue_spatial = _spatial_means(
        np.abs(blue_green).reshape(rows, columns, cell_height, cell_width)
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
            nuclear_y / max(cell_height - 1, 1),
            nuclear_x / max(cell_width - 1, 1),
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
            / max(cell_height - 1, 1)
            if sentinel_total
            else 0.0,
            (sum(value[2] for value in sentinel_values_raw) / sentinel_total)
            / max(cell_width - 1, 1)
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
            (
                cell_x * cell_width,
                cell_y * cell_height,
                cell_width,
                cell_height,
            )
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


def compute_cell_acceptance_batch(
    rgb: np.ndarray,
    grid: PhysicalGrid,
    cell_size: int,
) -> CellAcceptanceBatch | None:
    return _compute_rectangular_cell_acceptance_batch(
        rgb, grid, cell_size, cell_size
    )


def compute_partitioned_cell_acceptance_batch(
    rgb: np.ndarray,
    grid: PhysicalGrid,
    cell_size: int,
) -> CellAcceptanceBatch | None:
    """Batch full and partial edge cells without changing their physical bounds."""
    pixels = np.asarray(rgb)
    if (
        pixels.dtype != np.uint8
        or pixels.ndim != 3
        or pixels.shape[2] != 3
        or cell_size < 4
    ):
        return None
    height, width, _ = pixels.shape
    core_height = height - height % cell_size
    core_width = width - width % cell_size
    parts: list[tuple[int, int, CellAcceptanceBatch]] = []

    def add_part(
        values: np.ndarray,
        y_offset: int,
        x_offset: int,
        cell_height: int,
        cell_width: int,
    ) -> bool:
        if not values.size:
            return True
        batch = _compute_rectangular_cell_acceptance_batch(
            values, grid, cell_height, cell_width
        )
        if batch is None:
            return False
        parts.append((x_offset, y_offset, batch))
        return True

    remainder_height = height - core_height
    remainder_width = width - core_width
    requests = []
    if core_height and core_width:
        requests.append(
            (pixels[:core_height, :core_width], 0, 0, cell_size, cell_size)
        )
    if core_height and remainder_width:
        requests.append(
            (
                pixels[:core_height, core_width:],
                0,
                core_width,
                cell_size,
                remainder_width,
            )
        )
    if remainder_height and core_width:
        requests.append(
            (
                pixels[core_height:, :core_width],
                core_height,
                0,
                remainder_height,
                cell_size,
            )
        )
    if remainder_height and remainder_width:
        requests.append(
            (
                pixels[core_height:, core_width:],
                core_height,
                core_width,
                remainder_height,
                remainder_width,
            )
        )
    if not requests or any(not add_part(*request) for request in requests):
        return None

    records = []
    for x_offset, y_offset, batch in parts:
        for index, (x, y, cell_width, cell_height) in enumerate(batch.bounds):
            records.append(
                (
                    (x + x_offset, y + y_offset, cell_width, cell_height),
                    tuple((name, values[index]) for name, values in batch.groups),
                )
            )
    records.sort(key=lambda item: (item[0][1], item[0][0]))
    names = tuple(name for name, _values in records[0][1])
    return CellAcceptanceBatch(
        tuple(bounds for bounds, _groups in records),
        tuple(
            (
                name,
                np.stack(
                    [dict(groups)[name] for _bounds, groups in records], axis=0
                ),
            )
            for name in names
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
