from __future__ import annotations

from dataclasses import dataclass, field
import os
import sys
from pathlib import Path


PRIVATE_DIRECTORIES = (
    "sources",
    "secrets",
    "manifests",
    "scratch",
    "containers",
    "results",
    "quarantine",
    "checkpoints",
)


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _pid_identity(pid: int) -> str:
    """Return a namespace-local process birth marker when the OS exposes one."""

    if sys.platform.startswith("linux"):
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields_after_name = raw.rsplit(")", 1)[1].split()
            start_ticks = fields_after_name[19]
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
                encoding="ascii"
            ).strip()
            return f"linux:{boot_id}:{start_ticks}"
        except (OSError, IndexError):
            pass
    return f"pid:{pid}"


@dataclass(frozen=True, slots=True)
class RunLayout:
    repo_root: Path
    run_root: Path
    directories: tuple[str, ...] = field(default=PRIVATE_DIRECTORIES, init=False)

    def __post_init__(self) -> None:
        repo = Path(self.repo_root).resolve()
        run = Path(self.run_root).resolve()
        if repo == run or _contains(repo, run) or _contains(run, repo):
            raise ValueError("repository and private run roots must be disjoint")
        object.__setattr__(self, "repo_root", repo)
        object.__setattr__(self, "run_root", run)

    def ensure(self) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)
        for name in self.directories:
            (self.run_root / name).mkdir(parents=True, exist_ok=True)

    def resolve(self, directory: str, *parts: str) -> Path:
        if directory not in self.directories:
            raise ValueError("private path must use a declared run directory")
        target = (self.run_root / directory).joinpath(*parts).resolve()
        if not _contains(self.run_root, target):
            raise ValueError("private path escape is forbidden")
        if _contains(self.repo_root, target):
            raise ValueError("private path may not resolve beneath repository")
        return target


@dataclass(slots=True)
class PrivateRunLock:
    layout: RunLayout
    name: str
    _path: Path | None = field(default=None, init=False)
    _token: str = field(default="", init=False)

    def __enter__(self) -> PrivateRunLock:
        if not self.name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in self.name):
            raise ValueError("private lock name is invalid")
        self.layout.ensure()
        path = self.layout.resolve("checkpoints", f"{self.name}.lock")
        pid = os.getpid()
        token = f"{pid}|{_pid_identity(pid)}\n"
        for _attempt in range(2):
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    lock_token = path.read_text(encoding="ascii").strip()
                    pid_text, separator, identity = lock_token.partition("|")
                    locked_pid = int(pid_text)
                except (OSError, ValueError):
                    path.unlink(missing_ok=True)
                    continue
                if not _pid_is_alive(locked_pid) or (
                    separator and _pid_identity(locked_pid) != identity
                ):
                    path.unlink(missing_ok=True)
                    continue
                raise RuntimeError(f"private {self.name} writer is already active")
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            self._path = path
            self._token = token
            return self
        raise RuntimeError(f"private {self.name} lock could not be acquired")

    def __exit__(self, *_exc: object) -> None:
        if self._path is not None:
            try:
                if self._path.read_text(encoding="ascii") == self._token:
                    self._path.unlink(missing_ok=True)
            finally:
                self._path = None
