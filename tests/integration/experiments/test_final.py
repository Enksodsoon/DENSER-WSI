from __future__ import annotations

from pathlib import Path
import threading
import time

import numpy as np

import denser.experiments.candidate_selection as selection_module
from denser.codecs.lossless import SharedLosslessCodec
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


def lossless_standard(tile, ladder):  # type: ignore[no-untyped-def]
    return [SharedLosslessCodec().encode(tile)]


def no_quadtree(tile, sensitivity):  # type: ignore[no-untyped-def]
    return []


def test_final_encodes_every_level0_tile_once(tmp_path: Path) -> None:
    active_readers = 0
    maximum_readers = 0
    total_reads = 0
    lock = threading.Lock()

    def read_tile(address):
        nonlocal active_readers, maximum_readers, total_reads
        with lock:
            active_readers += 1
            total_reads += 1
            maximum_readers = max(maximum_readers, active_readers)
        time.sleep(0.005)
        with lock:
            active_readers -= 1
        return np.full((address.height, address.width, 3), 120, dtype=np.uint8)

    slide = FinalSlideInput("synthetic-final", 1025, 513, 512, read_tile)
    row = SlideRecord("synthetic-final", "SYNTHETIC", "4" * 64, "5" * 64, 1, "final", None)
    manifest = PartitionManifest("MC-V1-manifest-1", 9, (row,), "e" * 64)
    context = freeze_context()
    result = run_final_holdout(
        FinalHoldoutConfig(
            tmp_path,
            (slide,),
            context,
            standard_builder=lossless_standard,
            quadtree_builder=no_quadtree,
        ),
        manifest,
        create_freeze_record(context),
    )
    expected = set(iter_level0_grid(1025, 513, 512))
    assert result.encoded_addresses == expected
    assert all(count == 1 for count in result.address_method_counts.values())
    assert len(result.address_method_counts) == len(expected) * 3
    assert {key[0] for key in result.address_method_counts} == {"synthetic-final"}
    assert result.ledgers_match_files
    assert result.random_tiles_independently_decodable
    assert 1 < maximum_readers <= 3
    assert total_reads == len(expected)


def test_final_forbids_sample_extrapolation(tmp_path: Path) -> None:
    config = FinalHoldoutConfig(
        tmp_path,
        (),
        freeze_context(),
        standard_builder=lossless_standard,
        quadtree_builder=no_quadtree,
    )
    assert not config.sampled_tile_extrapolation_for_primary_endpoint_allowed


def test_final_skips_certificates_for_byte_dominated_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    calls = 0
    real_build = selection_module.build_certificate

    def counted_build(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(selection_module, "build_certificate", counted_build)
    slide = FinalSlideInput(
        "one-tile",
        8,
        8,
        8,
        lambda address: np.full((address.height, address.width, 3), 120, dtype=np.uint8),
    )
    row = SlideRecord("one-tile", "SYNTHETIC", "4" * 64, "5" * 64, 1, "final", None)
    manifest = PartitionManifest("MC-V1-manifest-1", 9, (row,), "e" * 64)
    context = freeze_context()
    run_final_holdout(
        FinalHoldoutConfig(
            tmp_path,
            (slide,),
            context,
            standard_builder=lossless_standard,
            quadtree_builder=no_quadtree,
        ),
        manifest,
        create_freeze_record(context),
    )
    assert calls == 7
