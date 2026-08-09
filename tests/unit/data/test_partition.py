from __future__ import annotations

from collections import defaultdict

import pytest

from denser.data.manifest import ManifestCandidate, PartitionPlan
from denser.data.partition import (
    DuplicateSourceError,
    assign_partitions,
    select_replacement,
)


def _candidate(index: int, case: str, project: str = "TCGA-LUAD") -> ManifestCandidate:
    return ManifestCandidate(
        research_id=f"RS-{index:03d}",
        project_id=project,
        case_id=case,
        source_sha256=f"{index:064x}",
        byte_count=100 + index,
    )


def _plan() -> PartitionPlan:
    return PartitionPlan(
        counts={"development": 2, "pilot": 2, "tuning": 1, "final": 2},
        reserve_count=2,
        run_salt=b"0123456789abcdef0123456789abcdef",
    )


def test_case_group_never_crosses_partitions() -> None:
    records = [_candidate(1, "case-a"), _candidate(2, "case-a")]
    records.extend(_candidate(index, f"case-{index}") for index in range(3, 12))
    manifest = assign_partitions(records, _plan(), 20260807)
    by_case: dict[str, set[str]] = defaultdict(set)
    for row in manifest.rows:
        by_case[row.case_group_sha256].add(row.partition)
    assert all(len(partitions) == 1 for partitions in by_case.values())


def test_partition_targets_count_slides_not_input_files() -> None:
    records = [_candidate(1, "case-a"), _candidate(2, "case-a")]
    records.extend(_candidate(index, f"case-{index}") for index in range(3, 11))
    manifest = assign_partitions(records, _plan(), 20260807)
    eligible = [row for row in manifest.rows if row.partition != "excluded"]
    expected = sum(_plan().counts.values()) + _plan().reserve_count
    assert len(eligible) == expected
    assert len({row.case_group_sha256 for row in eligible}) == len(eligible)


def test_assignment_is_deterministic_and_records_digest() -> None:
    records = [_candidate(index, f"case-{index}") for index in range(1, 12)]
    first = assign_partitions(records, _plan(), 20260807)
    second = assign_partitions(list(reversed(records)), _plan(), 20260807)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert len(first.manifest_sha256) == 64


def test_replacement_comes_from_prefrozen_reserve() -> None:
    records = [_candidate(index, f"case-{index}") for index in range(1, 12)]
    manifest = assign_partitions(records, _plan(), 20260807)
    result = select_replacement(manifest, "pilot", "decode_failure")
    assert result.replacement_rank == 1
    assert result.partition == "pilot"
    assert result.reason_code == "decode_failure"
    assert result.outcome_inspected is False


def test_exact_source_duplicate_is_rejected() -> None:
    records = [_candidate(1, "case-a"), _candidate(1, "case-b")]
    with pytest.raises(DuplicateSourceError, match="source SHA-256"):
        assign_partitions(records, _plan(), 20260807)


def test_insufficient_case_groups_fails_closed() -> None:
    with pytest.raises(ValueError, match="insufficient"):
        assign_partitions([_candidate(1, "case-a")], _plan(), 20260807)
