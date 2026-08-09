from __future__ import annotations

from pathlib import Path
import threading
import time

import numpy as np
import pytest

import denser.experiments.candidate_selection as selection_module
from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry
from denser.core.models import ByteBreakdown
from denser.data.manifest import PartitionManifest, SlideRecord
from denser.experiments.final import (
    FinalContainerResult,
    FinalHoldoutConfig,
    FinalSlideInput,
    iter_level0_grid,
    run_final_holdout,
    select_random_access_probes,
    summarize_final_performance,
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
            cpu_workers=2,
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
    assert all(container.encoding_seconds > 0 for container in result.containers)
    assert all(container.random_probe_count == len(expected) for container in result.containers)
    assert all(
        len(container.cold_decode_seconds) == len(expected)
        and len(container.warm_decode_seconds) == len(expected)
        for container in result.containers
    )
    assert maximum_readers == 2
    assert total_reads == len(expected)
    resumed = run_final_holdout(
        FinalHoldoutConfig(
            tmp_path,
            (slide,),
            context,
            cpu_workers=2,
            standard_builder=lossless_standard,
            quadtree_builder=no_quadtree,
        ),
        manifest,
        create_freeze_record(context),
    )
    assert total_reads == len(expected)
    assert resumed.ledgers_match_files
    assert resumed.random_tiles_independently_decodable
    assert [container.encoding_seconds for container in resumed.containers] == [
        container.encoding_seconds for container in result.containers
    ]


def test_final_uses_six_tile_workers_but_only_two_codec_builders(tmp_path: Path) -> None:
    active_builders = 0
    maximum_builders = 0
    lock = threading.Lock()

    def bounded_standard(tile, ladder):  # type: ignore[no-untyped-def]
        nonlocal active_builders, maximum_builders
        with lock:
            active_builders += 1
            maximum_builders = max(maximum_builders, active_builders)
        time.sleep(0.02)
        with lock:
            active_builders -= 1
        return [SharedLosslessCodec().encode(tile)]

    slide = FinalSlideInput(
        "parallel-final",
        48,
        8,
        8,
        lambda address: np.full((address.height, address.width, 3), 120, dtype=np.uint8),
    )
    row = SlideRecord("parallel-final", "SYNTHETIC", "4" * 64, "5" * 64, 1, "final", None)
    manifest = PartitionManifest("MC-V1-manifest-1", 9, (row,), "e" * 64)
    context = freeze_context()
    run_final_holdout(
        FinalHoldoutConfig(
            tmp_path,
            (slide,),
            context,
            cpu_workers=6,
            max_codec_subprocesses=2,
            standard_builder=bounded_standard,
            quadtree_builder=no_quadtree,
        ),
        manifest,
        create_freeze_record(context),
    )
    assert maximum_builders == 2


def test_random_access_probes_are_deterministic_and_not_endpoint_only() -> None:
    addresses = tuple(iter_level0_grid(4096, 4096, 512))
    first = select_random_access_probes(addresses, "f" * 64, "slide", 16)
    second = select_random_access_probes(addresses, "f" * 64, "slide", 16)
    assert first == second
    assert len(first) == 16
    assert len(set(first)) == 16
    assert set(first) != {addresses[0], addresses[-1]}


def test_final_performance_summary_uses_complete_method_observations(
    tmp_path: Path,
) -> None:
    containers = (
        FinalContainerResult("standard", tmp_path / "s1", 100, 2, 1.0, (1.0,), (2.0,)),
        FinalContainerResult("denser", tmp_path / "d1", 80, 2, 2.0, (2.0,), (4.0,)),
        FinalContainerResult("standard", tmp_path / "s2", 120, 2, 0.5, (1.0,), (2.0,)),
        FinalContainerResult("denser", tmp_path / "d2", 90, 2, 1.0, (2.0,), (4.0,)),
    )
    summary = summarize_final_performance(containers)
    assert summary.encoding_time_ratio == 2.0
    assert summary.cold_decode_p95_ratio == 2.0
    assert summary.warm_decode_p95_ratio == 2.0
    assert summary.random_probe_observations == 4


def test_final_forbids_sample_extrapolation(tmp_path: Path) -> None:
    config = FinalHoldoutConfig(
        tmp_path,
        (),
        freeze_context(),
        standard_builder=lossless_standard,
        quadtree_builder=no_quadtree,
    )
    assert not config.sampled_tile_extrapolation_for_primary_endpoint_allowed
    assert config.candidate_workers == 1
    with pytest.raises(ValueError, match="candidate workers"):
        FinalHoldoutConfig(
            tmp_path,
            (),
            freeze_context(),
            candidate_workers=7,
            standard_builder=lossless_standard,
            quadtree_builder=no_quadtree,
        )


def test_final_can_drop_debug_address_maps_without_dropping_grid_validation(
    tmp_path: Path,
) -> None:
    slide = FinalSlideInput(
        "compact-final",
        513,
        513,
        512,
        lambda address: np.full(
            (address.height, address.width, 3), 120, dtype=np.uint8
        ),
    )
    row = SlideRecord("compact-final", "SYNTHETIC", "4" * 64, "5" * 64, 1, "final", None)
    manifest = PartitionManifest("MC-V1-manifest-1", 9, (row,), "e" * 64)
    context = freeze_context()
    result = run_final_holdout(
        FinalHoldoutConfig(
            tmp_path,
            (slide,),
            context,
            cpu_workers=1,
            standard_builder=lossless_standard,
            quadtree_builder=no_quadtree,
            retain_address_debug_evidence=False,
        ),
        manifest,
        create_freeze_record(context),
    )
    assert result.encoded_addresses == set()
    assert result.address_method_counts == {}
    assert all(container.tile_count == 4 for container in result.containers)
    assert result.ledgers_match_files


def test_final_source_extension_reuses_standard_and_selects_smaller_exact_packet(
    tmp_path: Path,
) -> None:
    tile = np.full((8, 8, 3), 91, dtype=np.uint8)
    registry = CodecRegistry()
    registry.register(
        "fixture-source", lambda payload, allocation, shape, profile: tile.copy()
    )
    slide = FinalSlideInput(
        "one-tile",
        8,
        8,
        8,
        lambda address: tile.copy(),
        source_candidate_builder=lambda address: EncodedCandidate(
            "fixture-source", "source-extension", b"x", ByteBreakdown(payload=1)
        ),
    )
    row = SlideRecord("one-tile", "SYNTHETIC", "4" * 64, "5" * 64, 1, "final", None)
    manifest = PartitionManifest("MC-V1-manifest-1", 9, (row,), "e" * 64)
    context = freeze_context()
    result = run_final_holdout(
        FinalHoldoutConfig(
            tmp_path,
            (slide,),
            context,
            methods=("standard", "denser"),
            cpu_workers=1,
            standard_builder=lossless_standard,
            codec_registry=registry,
        ),
        manifest,
        create_freeze_record(context),
    )
    assert len(result.address_method_counts) == 2
    sizes = {container.method: container.complete_bytes for container in result.containers}
    assert sizes["denser"] < sizes["standard"]
    assert result.random_tiles_independently_decodable


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
    # One bound fallback certificate is shared by every method for the tile.
    assert calls == 5
