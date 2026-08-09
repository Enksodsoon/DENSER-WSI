from __future__ import annotations

import hashlib
import json
from pathlib import Path

from denser.codecs.standard import ladder_from_profile_ids
from denser.core.canonical import canonical_json_bytes
from denser.experiments.freeze import FreezeContext
from denser.governance.run_layout import RunLayout


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _tree_digest(root: Path, paths: list[Path]) -> str:
    records = []
    for path in sorted(paths):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _file_digest(path),
            }
        )
    return hashlib.sha256(canonical_json_bytes(records)).hexdigest()


def _dependency_versions(lock: dict[str, object]) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for name, record in sorted(lock.items()):
        if isinstance(record, str):
            version = record
        elif isinstance(record, dict) and isinstance(record.get("version"), str):
            version = record["version"]
        else:
            continue
        values.append((name, version))
    if not values:
        raise ValueError("toolchain lock contains no dependency versions")
    return tuple(values)


def _standard_ladders(
    routing: dict[str, object], projects: set[str]
) -> tuple[tuple[str, tuple[float, ...]], ...]:
    raw_routes = routing.get("routes")
    if not isinstance(raw_routes, dict) or set(raw_routes) != projects:
        raise ValueError("frozen standard routing does not match cohort projects")
    values: list[tuple[str, tuple[float, ...]]] = []
    for project in sorted(projects):
        profiles = raw_routes[project]
        if not isinstance(profiles, list):
            raise ValueError("frozen standard route is invalid")
        ladder = ladder_from_profile_ids(tuple(str(profile) for profile in profiles))
        for family, family_values in (
            ("jpeg", ladder.jpeg_qualities),
            ("jpeg2000", ladder.jpeg2000_ratios),
            ("jpegxl", ladder.jpegxl_distances),
            ("avif", ladder.avif_qualities),
        ):
            if family_values:
                values.append(
                    (f"{project}:{family}", tuple(float(value) for value in family_values))
                )
    return tuple(values)


def runtime_freeze_paths(repo_root: Path) -> tuple[Path, ...]:
    repo = Path(repo_root)
    paths = list((repo / "src" / "denser").rglob("*.py"))
    paths.extend(
        path
        for path in (
            repo / "scripts" / "run_private_final.py",
            repo / "scripts" / "analyze_private_final.py",
            repo / "scripts" / "create_private_freeze.py",
        )
        if path.exists()
    )
    return tuple(sorted(paths))


def build_runtime_freeze_context(
    repo_root: Path,
    run_root: Path,
    *,
    generation: int,
    git_commit: str,
    dirty_tree: bool,
    container_image_digest: str,
) -> FreezeContext:
    repo = Path(repo_root).resolve(strict=True)
    layout = RunLayout(repo, run_root)
    manifest_path = layout.resolve(
        "manifests", f"generation-{generation}-selected-sources.private.json"
    )
    routing_path = layout.resolve(
        "manifests", f"generation-{generation}-standard-routing.private.json"
    )
    calibration_path = layout.resolve(
        "results", "development", f"generation-{generation}", "calibration-record.json"
    )
    sbom_path = layout.resolve(
        "results",
        "final",
        f"generation-{generation}",
        "software-bill-of-materials.spdx.json",
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("private generation manifest rows are invalid")
    final_rows = [row for row in rows if row.get("partition") == "final"]
    reserve_rows = [row for row in rows if row.get("partition") == "reserve"]
    if len(final_rows) != 18 or len(reserve_rows) < 1:
        raise ValueError("freeze requires the reduced final cohort and prefrozen reserves")
    if len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("freeze manifest cases are not disjoint")
    if any(not 0.20 <= float(row.get("mpp", 0)) <= 0.30 for row in rows):
        raise ValueError("freeze manifest contains a source outside the primary MPP band")
    projects = {str(row["project_id"]) for row in final_rows}
    routing = json.loads(routing_path.read_text(encoding="utf-8"))
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if calibration.get("generation") != generation:
        raise ValueError("calibration generation does not match freeze generation")
    if calibration.get("harmful_control_audit", {}).get("status") != "calibrated":
        raise ValueError("freeze requires a passing harmful-control calibration")
    for partition in ("development", "pilot", "tuning"):
        result_root = layout.resolve("results", partition, f"generation-{generation}")
        matches = list(result_root.glob("feasibility-*.private.json"))
        if not matches:
            raise ValueError(f"freeze requires completed {partition} feasibility evidence")
        if not any(json.loads(path.read_text(encoding="utf-8")).get("source_data_processed") for path in matches):
            raise ValueError(f"freeze requires source-processed {partition} evidence")
    config_paths = [path for path in (repo / "configs").rglob("*.json")]
    configuration_records = [
        _tree_digest(repo, config_paths),
        _file_digest(routing_path),
        _file_digest(calibration_path),
    ]
    configuration_digest = hashlib.sha256(
        canonical_json_bytes(configuration_records)
    ).hexdigest()
    profile_document = {
        "profile_id": "mc-v2-source-segment-mosaic-v2-with-routed-standard-min",
        "methods": ["standard", "denser"],
        "source_segment_codec": "source-segment-mosaic-v2",
        "routing_sha256": _file_digest(routing_path),
        "calibration_sha256": calibration["calibration"]["sha256"],
        "novelty_hypothesis_sha256": _file_digest(
            repo / "configs" / "experiment" / "novelty_hypothesis.json"
        ),
    }
    evidence_paths = [path for path in (repo / "src" / "denser" / "evidence").rglob("*.py")]
    runtime_paths = list(runtime_freeze_paths(repo))
    thresholds = calibration["calibration"].get("thresholds")
    if not isinstance(thresholds, list):
        raise ValueError("calibration thresholds are invalid")
    lock = json.loads(
        (repo / "configs" / "toolchain" / "toolchain.lock.json").read_text(
            encoding="utf-8"
        )
    )
    return FreezeContext(
        git_commit=git_commit,
        dirty_tree=dirty_tree,
        container_image_digest=container_image_digest,
        sbom_digest=_file_digest(sbom_path),
        dependency_versions=_dependency_versions(lock),
        configuration_digest=configuration_digest,
        partition_manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
        reserve_manifest_digest=hashlib.sha256(
            canonical_json_bytes(reserve_rows)
        ).hexdigest(),
        selected_profile_id=str(profile_document["profile_id"]),
        profile_digest=hashlib.sha256(
            canonical_json_bytes(profile_document)
        ).hexdigest(),
        standard_candidate_ladders=_standard_ladders(routing, projects),
        evidence_tolerances=tuple(
            (str(item[0]), float(item[1])) for item in thresholds
        ),
        evidence_implementation_digest=_tree_digest(repo, evidence_paths),
        analysis_code_digest=_tree_digest(repo, runtime_paths),
        random_seeds=(20260808, 20260809),
        expected_final_slide_count=len(final_rows),
    )
