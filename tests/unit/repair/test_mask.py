from __future__ import annotations

from denser.repair.mask import RepairFailure, build_union_repair_mask


def overlapping_failures() -> list[RepairFailure]:
    return [
        RepairFailure(4, 4, 8, 8, image_width=24, image_height=24),
        RepairFailure(8, 8, 8, 8, image_width=24, image_height=24),
    ]


def test_overlapping_failed_cells_are_encoded_once() -> None:
    failures = overlapping_failures()
    mask = build_union_repair_mask(failures, halo_um=0.0, mpp=0.25)
    assert mask.pixel_count < sum(f.pixel_count for f in failures)
    assert mask.pixel_count == 112


def test_halo_is_converted_from_physical_units_and_clipped() -> None:
    failure = RepairFailure(0, 0, 2, 2, image_width=5, image_height=5)
    mask = build_union_repair_mask([failure], halo_um=0.5, mpp=0.25)
    assert mask.pixel_count == 16
    assert mask.shape == (5, 5)


def test_mask_encoding_is_deterministic() -> None:
    failures = overlapping_failures()
    first = build_union_repair_mask(failures, halo_um=2.0, mpp=0.25)
    second = build_union_repair_mask(reversed(failures), halo_um=2.0, mpp=0.25)
    assert first.encoded == second.encoded

