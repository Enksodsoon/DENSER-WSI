from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from denser.core.canonical import canonical_json_bytes


class StateIntegrityError(RuntimeError):
    """Execution state or its digest sidecar failed integrity validation."""


@dataclass(slots=True)
class ExecutionState:
    version: str = "DENSER-execution-state-1"
    committed_steps: list[str] = field(default_factory=list)
    completed_phases: list[str] = field(default_factory=list)
    in_progress_step: str | None = None
    attempts: dict[str, int] = field(default_factory=dict)
    repeated_steps: list[str] = field(default_factory=list)
    complete: bool = False

    def document(self) -> dict[str, object]:
        return asdict(self)


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
        if temporary.exists():
            temporary.unlink()


def digest_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.sha256")


def save_execution_state(path: Path, state: ExecutionState) -> None:
    payload = canonical_json_bytes(state.document())
    _atomic_write(path, payload)
    digest = hashlib.sha256(payload).hexdigest().encode("ascii") + b"\n"
    _atomic_write(digest_path(path), digest)


def load_execution_state(path: Path) -> ExecutionState:
    try:
        payload = path.read_bytes()
        expected = digest_path(path).read_text(encoding="ascii").strip()
    except OSError as error:
        raise StateIntegrityError("execution state or digest sidecar is missing") from error
    actual = hashlib.sha256(payload).hexdigest()
    if expected != actual:
        raise StateIntegrityError("execution state digest mismatch")
    try:
        document = json.loads(payload)
        state = ExecutionState(**document)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise StateIntegrityError("execution state document is invalid") from error
    if state.version != "DENSER-execution-state-1":
        raise StateIntegrityError("execution state version is unsupported")
    return state
