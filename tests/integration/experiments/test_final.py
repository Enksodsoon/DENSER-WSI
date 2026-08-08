from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from denser.data.manifest import PartitionManifest, SlideRecord
from denser.experiments.final import (
    FinalHoldoutConfig,
    FinalSlideInput,
    iter_level0_grid,
    run_final_holdout,
)
from denser.experiments.freeze import FreezeContext, create_freeze_record


def freeze_context() -> FreezeContext:
    return FreezeContext(
        "a" * 40, False, "sha256:" + "b" * 64, "c" * 64,
        (("python", "3.12.13"),), "d" * 64, "e" * 64, "f" * 64,
        "DENSER-P3", "1" * 64, (("jpeg", (70.0,)),), (("visual", 1.0),),
        "2" * 64, "3" * 64, (9,), 1,
    )


def test_final_encodes_every_level0_tile_once(tmp_path: Path) -> None:
    def read_tile(address):
        return np.full((address.height, address.width, 3), 120, dtype=np.uint8)

    slide = FinalSlideInput("synthetic-final", 1025, 513, 512, read_tile)
    row = SlideRecord("synthetic-final", "SYNTHETIC", "4" * 64, "5" * 64, 1, "final", None)
    manifest = PartitionManifest("MC-V1-manifest-1", 9, (row,), "e" * 64)
    context = freeze_context()
    result = run_final_holdout(
        FinalHoldoutConfig(tmp_path, (slide,), context), manifest, create_freeze_record(context)
    )
    expected = set(iter_level0_grid(1025, 513, 512))
    assert result.encoded_addresses == expected
    assert all(count == 1 for count in result.address_method_counts.values())
    assert len(result.address_method_counts) == len(expected) * 3
    assert result.ledgers_match_files
    assert result.random_tiles_independently_decodable


def test_final_forbids_sample_extrapolation(tmp_path: Path) -> None:
    config = FinalHoldoutConfig(tmp_path, (), freeze_context())
    assert not config.sampled_tile_extrapolation_for_primary_endpoint_allowed
