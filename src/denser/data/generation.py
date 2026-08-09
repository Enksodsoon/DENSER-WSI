from __future__ import annotations

import hashlib
import hmac
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from denser.core.canonical import canonical_json_bytes
from denser.data.models import GdcSlideRecord
from denser.wsi.metadata import MetadataError
from denser.wsi.remote_metadata import RemotePhysicalMetadata


REDUCED_PROJECT_SEQUENCE = (
    "development",
    "pilot",
    "tuning",
    "final",
    "final",
    "final",
    "reserve",
    "reserve",
)


class InsufficientEligibleCohort(RuntimeError):
    """A project cannot fill the predeclared scale-eligible generation quota."""


@dataclass(frozen=True, slots=True)
class GenerationSelection:
    manifest: dict[str, object]
    audit: dict[str, object]


def _digest_key(salt: bytes, *parts: str) -> str:
    return hmac.new(salt, "\0".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def _research_id(salt: bytes, file_uuid: str) -> str:
    return f"RS-{_digest_key(salt, 'research-id', file_uuid)[:24]}"


def select_scale_verified_generation(
    records: Iterable[GdcSlideRecord],
    *,
    projects: tuple[str, ...],
    excluded_case_ids: set[str],
    excluded_file_uuids: set[str],
    salt: bytes,
    seed: int,
    probe: Callable[[str], RemotePhysicalMetadata],
    partition_sequence: tuple[str, ...] = REDUCED_PROJECT_SEQUENCE,
) -> GenerationSelection:
    if len(salt) < 32:
        raise ValueError("generation cohort salt must contain at least 32 bytes")
    if not projects or len(set(projects)) != len(projects):
        raise ValueError("generation projects must be unique and nonempty")
    if not partition_sequence or any(
        value not in {"development", "pilot", "tuning", "final", "reserve"}
        for value in partition_sequence
    ):
        raise ValueError("generation partition sequence is invalid")
    by_project_case: dict[str, dict[str, list[GdcSlideRecord]]] = {
        project: defaultdict(list) for project in projects
    }
    for record in records:
        if (
            record.project_id not in by_project_case
            or record.case_id in excluded_case_ids
            or record.file_uuid in excluded_file_uuids
            or record.access != "open"
        ):
            continue
        by_project_case[record.project_id][record.case_id].append(record)

    rows: list[dict[str, object]] = []
    project_audit: list[dict[str, object]] = []
    for project in projects:
        case_groups = sorted(
            by_project_case[project].items(),
            key=lambda item: _digest_key(salt, str(seed), project, item[0]),
        )
        selected: list[tuple[GdcSlideRecord, RemotePhysicalMetadata]] = []
        probed_files = 0
        outside_band = 0
        unresolved = 0
        for case_id, files in case_groups:
            ordered_files = sorted(
                files,
                key=lambda record: _digest_key(
                    salt, str(seed), project, case_id, record.file_uuid
                ),
            )
            for record in ordered_files:
                probed_files += 1
                url = f"https://api.gdc.cancer.gov/data/{record.file_uuid}"
                try:
                    metadata = probe(url)
                except (OSError, MetadataError):
                    unresolved += 1
                    continue
                if not 0.20 <= metadata.mpp <= 0.30:
                    outside_band += 1
                    continue
                selected.append((record, metadata))
                break
            if len(selected) == len(partition_sequence):
                break
        if len(selected) != len(partition_sequence):
            raise InsufficientEligibleCohort(
                f"project {project} has {len(selected)} scale-eligible case groups; "
                f"{len(partition_sequence)} required"
            )
        for assignment_ordinal, ((record, metadata), partition) in enumerate(
            zip(selected, partition_sequence, strict=True)
        ):
            rows.append(
                {
                    "access": "open",
                    "case_id": record.case_id,
                    "file_name": record.file_name,
                    "file_size": record.file_size,
                    "file_uuid": record.file_uuid,
                    "md5": record.md5,
                    "mpp": round(metadata.mpp, 12),
                    "partition": partition,
                    "project_id": project,
                    "research_id": _research_id(salt, record.file_uuid),
                    "source_url": f"https://api.gdc.cancer.gov/data/{record.file_uuid}",
                    "selection_ordinal": assignment_ordinal,
                    "scale_metadata_source": metadata.source,
                }
            )
        project_audit.append(
            {
                "project_id": project,
                "probed_files": probed_files,
                "selected_case_groups": len(selected),
                "outside_primary_band": outside_band,
                "unresolved_metadata": unresolved,
            }
        )
    rows.sort(
        key=lambda row: (
            str(row["project_id"]),
            int(row["selection_ordinal"]),
        )
    )
    unsigned = {
        "version": "DENSER-private-source-manifest-2-scale-prefiltered",
        "generation": 2,
        "seed": seed,
        "selection_design": "case-disjoint-hmac-order-primary-mpp-prefilter-v1",
        "rows": rows,
    }
    manifest = {
        **unsigned,
        "sha256": hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest(),
    }
    audit = {
        "version": "DENSER-private-generation-selection-audit-1",
        "generation": 2,
        "compression_outcomes_inspected": False,
        "excluded_prior_case_count": len(excluded_case_ids),
        "selected_count": len(rows),
        "partition_counts": {
            name: sum(row["partition"] == name for row in rows)
            for name in ("development", "pilot", "tuning", "final", "reserve")
        },
        "projects": project_audit,
        "manifest_sha256": manifest["sha256"],
    }
    return GenerationSelection(manifest, audit)
