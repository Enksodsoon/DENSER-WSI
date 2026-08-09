from __future__ import annotations

from denser.data.generation import select_scale_verified_generation
from denser.data.models import GdcSlideRecord
from denser.wsi.remote_metadata import RemotePhysicalMetadata


def _record(index: int, project: str, case: str) -> GdcSlideRecord:
    return GdcSlideRecord(
        f"ignored-{index}",
        f"file-{index}",
        f"slide-{index}.svs",
        project,
        case,
        None,
        "H&E",
        None,
        None,
        100 + index,
        f"{index:032x}",
        None,
        "open",
    )


def test_generation_selection_is_deterministic_scale_filtered_and_case_disjoint() -> None:
    records = [
        _record(0, "TCGA-A", "prior-case"),
        _record(1, "TCGA-A", "case-1"),
        _record(2, "TCGA-A", "case-2"),
        _record(3, "TCGA-A", "case-3"),
        _record(4, "TCGA-B", "case-4"),
        _record(5, "TCGA-B", "case-5"),
        _record(6, "TCGA-B", "case-6"),
    ]

    def probe(url: str) -> RemotePhysicalMetadata:
        mpp = 0.50 if url.endswith("file-2") else 0.25
        return RemotePhysicalMetadata(mpp, 100, "fixture")

    kwargs = {
        "projects": ("TCGA-A", "TCGA-B"),
        "excluded_case_ids": {"prior-case"},
        "excluded_file_uuids": set(),
        "salt": b"s" * 32,
        "seed": 7,
        "probe": probe,
        "partition_sequence": ("development", "final"),
    }
    first = select_scale_verified_generation(records, **kwargs)
    second = select_scale_verified_generation(reversed(records), **kwargs)
    assert first == second
    rows = first.manifest["rows"]
    assert len(rows) == 4
    assert all(row["case_id"] != "prior-case" for row in rows)
    assert all(row["mpp"] == 0.25 for row in rows)
    assert len({row["case_id"] for row in rows}) == 4
    assert first.audit["compression_outcomes_inspected"] is False
    assert first.audit["partition_counts"]["final"] == 2
