from __future__ import annotations

import hashlib
import hmac
from collections import defaultdict
from dataclasses import replace

from denser.core.hashes import sha256_bytes
from denser.data.manifest import (
    PARTITIONS,
    ManifestCandidate,
    PartitionManifest,
    PartitionPlan,
    SlideRecord,
)


class DuplicateSourceError(ValueError):
    """The candidate list contains identical physical source bytes."""


def _case_hash(case_id: str, salt: bytes) -> str:
    return hmac.new(salt, case_id.encode("utf-8"), hashlib.sha256).hexdigest()


def _order_key(seed: int, project_id: str, case_hash: str) -> str:
    material = f"{seed}\0{project_id}\0{case_hash}".encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _validate_candidates(records: list[ManifestCandidate]) -> None:
    seen_sources: set[str] = set()
    for record in records:
        try:
            valid_hash = len(record.source_sha256) == 64 and bytes.fromhex(
                record.source_sha256
            ) is not None
        except ValueError:
            valid_hash = False
        if not valid_hash:
            raise ValueError("source SHA-256 must be 64 hexadecimal characters")
        if record.source_sha256 in seen_sources:
            raise DuplicateSourceError("duplicate source SHA-256 detected")
        seen_sources.add(record.source_sha256)


def assign_partitions(
    records: list[ManifestCandidate], plan: PartitionPlan, seed: int
) -> PartitionManifest:
    _validate_candidates(records)
    groups: dict[tuple[str, str], list[ManifestCandidate]] = defaultdict(list)
    for record in records:
        groups[(record.project_id, _case_hash(record.case_id, plan.run_salt))].append(
            record
        )
    needed = sum(plan.counts.values()) + plan.reserve_count
    if len(groups) < needed:
        raise ValueError("insufficient case groups for partition and reserve plan")

    ordered_groups = sorted(
        groups.items(), key=lambda item: _order_key(seed, item[0][0], item[0][1])
    )
    remaining = dict(plan.counts)
    project_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {partition: 0 for partition in PARTITIONS}
    )
    assignments: dict[tuple[str, str], tuple[str, int | None]] = {}
    reserve_rank = 0
    for key, _group in ordered_groups:
        project_id, _case_group = key
        available = [partition for partition in PARTITIONS if remaining[partition] > 0]
        if available:
            partition = min(
                available,
                key=lambda name: (
                    project_counts[project_id][name] / max(plan.counts[name], 1),
                    PARTITIONS.index(name),
                ),
            )
            remaining[partition] -= 1
            project_counts[project_id][partition] += 1
            assignments[key] = (partition, None)
        elif reserve_rank < plan.reserve_count:
            reserve_rank += 1
            assignments[key] = ("reserve", reserve_rank)
        else:
            assignments[key] = ("excluded", None)

    rows: list[SlideRecord] = []
    for key, group in ordered_groups:
        partition, rank = assignments[key]
        record = min(group, key=lambda item: (item.source_sha256, item.research_id))
        rows.append(
            SlideRecord(
                research_id=record.research_id,
                project_id=record.project_id,
                case_group_sha256=key[1],
                source_sha256=record.source_sha256,
                byte_count=record.byte_count,
                partition=partition,
                replacement_rank=rank,
            )
        )
    unsigned = PartitionManifest("MC-V1-manifest-1", seed, tuple(rows), "")
    digest = sha256_bytes(unsigned.unsigned_bytes())
    return replace(unsigned, manifest_sha256=digest)


def select_replacement(
    manifest: PartitionManifest, partition: str, reason_code: str
) -> SlideRecord:
    if partition not in PARTITIONS:
        raise ValueError("replacement target must be an experiment partition")
    if not reason_code or "outcome" in reason_code.lower():
        raise ValueError("replacement reason must be outcome-independent")
    reserves = sorted(
        (row for row in manifest.rows if row.partition == "reserve"),
        key=lambda row: (row.replacement_rank or 0, row.research_id),
    )
    if not reserves:
        raise ValueError("prefrozen reserve is exhausted")
    return replace(
        reserves[0],
        partition=partition,
        reason_code=reason_code,
        outcome_inspected=False,
    )
