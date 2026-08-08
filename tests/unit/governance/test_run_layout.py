from __future__ import annotations

from pathlib import Path

import pytest

from denser.governance.run_layout import PrivateRunLock, RunLayout


def test_run_layout_creates_only_declared_private_directories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    run = tmp_path / "private-run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    layout.ensure()
    assert set(path.name for path in run.iterdir()) == set(layout.directories)
    assert layout.resolve("sources", "development", "slide.svs").is_relative_to(run)


def test_run_layout_rejects_repo_nested_in_private_root(tmp_path: Path) -> None:
    run = tmp_path / "private-run"
    repo = run / "repo"
    repo.mkdir(parents=True)
    with pytest.raises(ValueError, match="disjoint"):
        RunLayout(repo, run)


def test_run_layout_rejects_escape_and_unknown_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    run = tmp_path / "private-run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    with pytest.raises(ValueError, match="declared"):
        layout.resolve("unknown", "payload")
    with pytest.raises(ValueError, match="escape"):
        layout.resolve("sources", "..", "..", "repo")


def test_private_run_lock_prevents_concurrent_writer(tmp_path: Path) -> None:
    repo, run = tmp_path / "repo", tmp_path / "run"
    repo.mkdir()
    layout = RunLayout(repo, run)
    layout.ensure()
    with PrivateRunLock(layout, "download"):
        with pytest.raises(RuntimeError, match="already active"):
            with PrivateRunLock(layout, "download"):
                pass
    with PrivateRunLock(layout, "download"):
        pass
