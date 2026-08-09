from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from denser.core.canonical import canonical_json_bytes
from denser.core.errors import FreezeViolation


@dataclass(frozen=True, slots=True)
class FreezeContext:
    git_commit: str
    dirty_tree: bool
    container_image_digest: str
    sbom_digest: str
    dependency_versions: tuple[tuple[str, str], ...]
    configuration_digest: str
    partition_manifest_digest: str
    reserve_manifest_digest: str
    selected_profile_id: str
    profile_digest: str
    standard_candidate_ladders: tuple[tuple[str, tuple[float, ...]], ...]
    evidence_tolerances: tuple[tuple[str, float], ...]
    evidence_implementation_digest: str
    analysis_code_digest: str
    random_seeds: tuple[int, ...]
    expected_final_slide_count: int


@dataclass(frozen=True, slots=True)
class FreezeRecord:
    version: str
    git_commit: str
    clean_tree: bool
    container_image_digest: str
    sbom_digest: str
    dependency_versions: tuple[tuple[str, str], ...]
    configuration_digest: str
    partition_manifest_digest: str
    reserve_manifest_digest: str
    selected_profile_id: str
    profile_digest: str
    standard_candidate_ladders: tuple[tuple[str, tuple[float, ...]], ...]
    evidence_tolerances: tuple[tuple[str, float], ...]
    evidence_implementation_digest: str
    analysis_code_digest: str
    random_seeds: tuple[int, ...]
    expected_final_slide_count: int
    freeze_digest: str

    def unsigned_document(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("freeze_digest")
        return value


def _validate_context(context: FreezeContext) -> None:
    if context.dirty_tree:
        raise FreezeViolation("final freeze requires a clean Git tree")
    digests = (
        context.sbom_digest,
        context.configuration_digest,
        context.partition_manifest_digest,
        context.reserve_manifest_digest,
        context.profile_digest,
        context.evidence_implementation_digest,
        context.analysis_code_digest,
    )
    if any(len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value) for value in digests):
        raise FreezeViolation("freeze context contains an invalid SHA-256 digest")
    if len(context.git_commit) != 40 or context.expected_final_slide_count <= 0:
        raise FreezeViolation("freeze Git commit or final slide count is invalid")
    if not context.container_image_digest.startswith("sha256:"):
        raise FreezeViolation("container image must be pinned by SHA-256 digest")


def create_freeze_record(context: FreezeContext) -> FreezeRecord:
    _validate_context(context)
    unsigned = FreezeRecord(
        "DENSER-freeze-1",
        context.git_commit,
        True,
        context.container_image_digest,
        context.sbom_digest,
        context.dependency_versions,
        context.configuration_digest,
        context.partition_manifest_digest,
        context.reserve_manifest_digest,
        context.selected_profile_id,
        context.profile_digest,
        context.standard_candidate_ladders,
        context.evidence_tolerances,
        context.evidence_implementation_digest,
        context.analysis_code_digest,
        context.random_seeds,
        context.expected_final_slide_count,
        "",
    )
    digest = hashlib.sha256(canonical_json_bytes(unsigned.unsigned_document())).hexdigest()
    return replace(unsigned, freeze_digest=digest)


def verify_freeze_record(record: FreezeRecord, context: FreezeContext) -> None:
    expected = create_freeze_record(context)
    actual_digest = hashlib.sha256(canonical_json_bytes(record.unsigned_document())).hexdigest()
    if record.freeze_digest != actual_digest:
        raise FreezeViolation("freeze record digest mismatch")
    if record != expected:
        raise FreezeViolation("runtime context differs from the final freeze")


def freeze_record_from_dict(document: dict[str, object]) -> FreezeRecord:
    try:
        record = FreezeRecord(
            version=str(document["version"]),
            git_commit=str(document["git_commit"]),
            clean_tree=bool(document["clean_tree"]),
            container_image_digest=str(document["container_image_digest"]),
            sbom_digest=str(document["sbom_digest"]),
            dependency_versions=tuple(
                (str(item[0]), str(item[1]))
                for item in document["dependency_versions"]  # type: ignore[union-attr]
            ),
            configuration_digest=str(document["configuration_digest"]),
            partition_manifest_digest=str(document["partition_manifest_digest"]),
            reserve_manifest_digest=str(document["reserve_manifest_digest"]),
            selected_profile_id=str(document["selected_profile_id"]),
            profile_digest=str(document["profile_digest"]),
            standard_candidate_ladders=tuple(
                (str(item[0]), tuple(float(value) for value in item[1]))
                for item in document["standard_candidate_ladders"]  # type: ignore[union-attr]
            ),
            evidence_tolerances=tuple(
                (str(item[0]), float(item[1]))
                for item in document["evidence_tolerances"]  # type: ignore[union-attr]
            ),
            evidence_implementation_digest=str(document["evidence_implementation_digest"]),
            analysis_code_digest=str(document["analysis_code_digest"]),
            random_seeds=tuple(int(value) for value in document["random_seeds"]),  # type: ignore[union-attr]
            expected_final_slide_count=int(document["expected_final_slide_count"]),
            freeze_digest=str(document["freeze_digest"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise FreezeViolation("freeze record mapping is invalid") from error
    actual = hashlib.sha256(canonical_json_bytes(record.unsigned_document())).hexdigest()
    if record.version != "DENSER-freeze-1" or record.freeze_digest != actual:
        raise FreezeViolation("freeze record document digest is invalid")
    return record


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_freeze_record(path: Path, record: FreezeRecord) -> None:
    payload = canonical_json_bytes(asdict(record)) + b"\n"
    _atomic_write(path, payload)
    sidecar = hashlib.sha256(payload).hexdigest().encode("ascii") + b"\n"
    _atomic_write(path.with_name(f"{path.name}.sha256"), sidecar)
