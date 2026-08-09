from __future__ import annotations

import numpy as np
import pytest

from denser.evidence.architecture import (
    compare_acceptance,
    compute_acceptance_groups,
    compute_acceptance_evidence,
)
from denser.evidence.cell_batch import (
    compare_cell_acceptance_batches,
    compute_cell_acceptance_batch,
    compute_cell_acceptance_groups,
)
from denser.evidence.nuclei import nuclear_features
from denser.evidence.sentinels import sentinel_features
from denser.evidence.types import AcceptanceContract, PhysicalGrid
from denser.evidence.visual import visual_features


def _challenge_pair(control: str) -> tuple[np.ndarray, np.ndarray]:
    source = np.full((64, 64, 3), 250, dtype=np.uint8)
    y, x = np.mgrid[:64, :64]
    tissue = (x - 32) ** 2 + (y - 32) ** 2 <= 24**2
    nucleus = (x - 24) ** 2 + (y - 30) ** 2 <= 8**2
    lumen = (x - 39) ** 2 + (y - 33) ** 2 <= 6**2
    source[tissue] = [215, 145, 185]
    source[nucleus] = [85, 35, 105]
    source[lumen] = [252, 252, 252]
    source[16:18, 47:49] = [35, 20, 45]
    altered = source.copy()
    if control == "delete_small_dark_object":
        altered[16:18, 47:49] = [250, 250, 250]
    elif control == "shift_nuclear_boundary":
        altered[nucleus] = [215, 145, 185]
        shifted = (x - 29) ** 2 + (y - 30) ** 2 <= 6**2
        altered[shifted] = [85, 35, 105]
    elif control == "collapse_lumen":
        altered[lumen] = [215, 145, 185]
    else:
        raise ValueError(control)
    return source, altered


@pytest.mark.parametrize(
    ("control", "group"),
    [
        ("delete_small_dark_object", "rare_event_sentinels"),
        ("shift_nuclear_boundary", "nuclear_objects"),
        ("collapse_lumen", "architecture"),
    ],
)
def test_harmful_control_is_detected(control: str, group: str) -> None:
    source, altered = _challenge_pair(control)
    result = compare_acceptance(
        source, altered, PhysicalGrid(0.25, 0.25), AcceptanceContract()
    )
    assert group in result.failed_groups


def test_identical_image_passes_all_acceptance_groups() -> None:
    source, _ = _challenge_pair("collapse_lumen")
    result = compare_acceptance(
        source, source.copy(), PhysicalGrid(0.25, 0.25), AcceptanceContract()
    )
    assert result.failed_groups == ()


def test_object_and_sentinel_evidence_use_physical_area_not_pixel_area() -> None:
    fine = np.full((40, 40, 3), (215, 145, 185), dtype=np.uint8)
    coarse = np.full((20, 20, 3), (215, 145, 185), dtype=np.uint8)
    fine[16:24, 16:24] = (35, 20, 45)
    coarse[8:12, 8:12] = (35, 20, 45)
    fine_grid = PhysicalGrid(0.25, 0.25)
    coarse_grid = PhysicalGrid(0.50, 0.50)
    fine_nuclear = nuclear_features(fine, fine_grid)
    coarse_nuclear = nuclear_features(coarse, coarse_grid)
    fine_sentinel = sentinel_features(fine, fine_grid)
    coarse_sentinel = sentinel_features(coarse, coarse_grid)
    assert fine_nuclear[:2] == pytest.approx(coarse_nuclear[:2])
    assert fine_sentinel[:2] == pytest.approx(coarse_sentinel[:2])


def test_acceptance_evidence_can_compute_only_globally_failed_groups() -> None:
    rgb = np.full((16, 16, 3), 180, dtype=np.uint8)
    evidence = compute_acceptance_evidence(
        rgb,
        PhysicalGrid(0.25, 0.25),
        AcceptanceContract(),
        groups=("visual", "nuclear_objects"),
    )
    assert [name for name, _values in evidence.groups] == [
        "nuclear_objects",
        "visual",
    ]
    with pytest.raises(ValueError, match="acceptance group"):
        compute_acceptance_evidence(
            rgb,
            PhysicalGrid(0.25, 0.25),
            AcceptanceContract(),
            groups=("unknown",),
        )


def _reference_visual_features(rgb: np.ndarray) -> tuple[float, ...]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    features: list[float] = []
    for channel in range(3):
        histogram, _ = np.histogram(pixels[:, :, channel], bins=16, range=(0, 256))
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
    covariance = (
        np.cov(flattened, rowvar=False)
        if len(flattened) > 1
        else np.zeros((3, 3))
    )
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
    for y_indices in np.array_split(np.arange(height), 4):
        for x_indices in np.array_split(np.arange(width), 4):
            red_block = red_green[np.ix_(y_indices, x_indices)]
            blue_block = blue_green[np.ix_(y_indices, x_indices)]
            features.extend(
                (
                    float(np.mean(np.abs(red_block))) if red_block.size else 0.0,
                    float(np.mean(np.abs(blue_block))) if blue_block.size else 0.0,
                )
            )
    return tuple(features)


@pytest.mark.parametrize("shape", ((32, 32, 3), (31, 29, 3), (1, 1, 3)))
def test_fast_visual_features_preserve_reference_values(shape: tuple[int, int, int]) -> None:
    rgb = np.random.default_rng(19).integers(0, 256, shape, dtype=np.uint8)
    assert visual_features(rgb) == pytest.approx(
        _reference_visual_features(rgb), rel=1e-12, abs=1e-12
    )


def test_batched_cell_evidence_matches_scalar_reference() -> None:
    rgb = np.random.default_rng(23).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    grid = PhysicalGrid(0.25, 0.25)
    observed = compute_cell_acceptance_groups(rgb, grid, 16)
    assert observed is not None
    for y in range(0, 64, 16):
        for x in range(0, 64, 16):
            expected = compute_acceptance_groups(rgb[y : y + 16, x : x + 16], grid)
            actual = observed[(x, y, 16, 16)]
            assert [name for name, _values in actual] == [
                name for name, _values in expected
            ]
            for (_name, actual_values), (_other, expected_values) in zip(
                actual, expected, strict=True
            ):
                assert actual_values == pytest.approx(
                    expected_values, rel=1e-10, abs=1e-10
                )


def test_batched_cell_evidence_matches_scalar_for_physical_cell_33() -> None:
    rgb = np.random.default_rng(25).integers(0, 256, (66, 66, 3), dtype=np.uint8)
    grid = PhysicalGrid(0.2424, 0.2424)
    observed = compute_cell_acceptance_groups(rgb, grid, 33)
    assert observed is not None
    for y in range(0, 66, 33):
        for x in range(0, 66, 33):
            expected = compute_acceptance_groups(rgb[y : y + 33, x : x + 33], grid)
            actual = observed[(x, y, 33, 33)]
            for (_name, actual_values), (_other, expected_values) in zip(
                actual, expected, strict=True
            ):
                assert actual_values == pytest.approx(
                    expected_values, rel=1e-10, abs=1e-10
                )


def test_batched_cell_comparison_matches_scalar_contract() -> None:
    source = np.random.default_rng(24).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    candidate = source.copy()
    candidate[:32, :32] //= 2
    grid = PhysicalGrid(0.25, 0.25)
    contract = AcceptanceContract(0.03, 0.03, 0.01, 0.03)
    reference_batch = compute_cell_acceptance_batch(source, grid, 16)
    candidate_batch = compute_cell_acceptance_batch(candidate, grid, 16)
    assert reference_batch is not None and candidate_batch is not None
    observed = compare_cell_acceptance_batches(
        reference_batch, candidate_batch, contract
    )
    reference_groups = compute_cell_acceptance_groups(source, grid, 16)
    candidate_groups = compute_cell_acceptance_groups(candidate, grid, 16)
    assert reference_groups is not None and candidate_groups is not None
    for bounds, values in reference_groups.items():
        from denser.evidence.architecture import compare_acceptance_groups

        expected = compare_acceptance_groups(
            values, candidate_groups[bounds], contract
        ).failed_groups
        assert observed[bounds] == expected
