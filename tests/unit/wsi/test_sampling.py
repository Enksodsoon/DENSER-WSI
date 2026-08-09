from __future__ import annotations

import numpy as np

from denser.core.models import TileAddress
from denser.wsi.sampling import SamplingConfig, freeze_sample, measure_content


class _FakeSlide:
    level_dimensions = ((8, 8),)

    def __init__(self) -> None:
        self.tiles = {
            (0, 0): np.full((4, 4, 3), 255, dtype=np.uint8),
            (4, 0): np.vstack(
                [
                    np.full((2, 4, 3), [130, 70, 150], dtype=np.uint8),
                    np.full((2, 4, 3), 255, dtype=np.uint8),
                ]
            ),
            (0, 4): np.full((4, 4, 3), [130, 70, 150], dtype=np.uint8),
            (4, 4): np.zeros((4, 4, 3), dtype=np.uint8),
        }

    def read_level0_region(self, address: TileAddress) -> np.ndarray:
        return self.tiles[(address.x, address.y)].copy()


def test_sampling_is_frozen_before_codec_use() -> None:
    config = SamplingConfig(tile_size=4, samples_per_stratum=1)
    first = freeze_sample(_FakeSlide(), config, 7)
    second = freeze_sample(_FakeSlide(), config, 7)
    assert first.sha256 == second.sha256
    assert first.canonical_bytes() == second.canonical_bytes()


def test_sampling_includes_declared_content_strata_without_replacement() -> None:
    manifest = freeze_sample(
        _FakeSlide(), SamplingConfig(tile_size=4, samples_per_stratum=1), 7
    )
    assert {row.stratum for row in manifest.rows} == {
        "low_tissue", "mixed_tissue", "high_tissue", "artifact_enriched"
    }
    coordinates = [(row.address.x, row.address.y) for row in manifest.rows]
    assert len(coordinates) == len(set(coordinates))


def test_sampling_seed_changes_order_not_content_measurements() -> None:
    config = SamplingConfig(tile_size=4, samples_per_stratum=1)
    first = freeze_sample(_FakeSlide(), config, 1)
    second = freeze_sample(_FakeSlide(), config, 2)
    by_coordinate_a = {
        (row.address.x, row.address.y): (row.tissue_fraction, row.artifact_fraction)
        for row in first.rows
    }
    by_coordinate_b = {
        (row.address.x, row.address.y): (row.tissue_fraction, row.artifact_fraction)
        for row in second.rows
    }
    assert by_coordinate_a == by_coordinate_b


def test_uniform_gray_is_not_tissue() -> None:
    tissue, artifact, stratum = measure_content(
        np.full((512, 512, 3), 128, dtype=np.uint8)
    )
    assert tissue == 0.0
    assert artifact == 0.0
    assert stratum == "low_tissue"
