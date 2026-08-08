from __future__ import annotations

import json
from pathlib import Path

import pytest

from denser.orchestration.runner import PhaseRunner, SimulatedCrash
from denser.orchestration.state import StateIntegrityError, load_execution_state


def test_resume_reexecutes_only_uncommitted_atomic_step(tmp_path: Path) -> None:
    calls: list[str] = []

    def step(name: str):
        return lambda: calls.append(name)

    runner = PhaseRunner(
        tmp_path / "execution-state.json",
        [("foundation:1", step("foundation:1")), ("wsi_io:3", step("wsi_io:3")), ("analysis:1", step("analysis:1"))],
        crash_after="wsi_io:3",
    )
    with pytest.raises(SimulatedCrash):
        runner.run_all()
    resumed = runner.resume()
    assert resumed.repeated_steps == ("wsi_io:3",)
    assert calls == ["foundation:1", "wsi_io:3", "wsi_io:3", "analysis:1"]
    assert resumed.complete


def test_state_and_sidecar_digest_detect_tampering(tmp_path: Path) -> None:
    path = tmp_path / "execution-state.json"
    runner = PhaseRunner(path, [("foundation:1", lambda: None)])
    runner.run_all()
    document = json.loads(path.read_text(encoding="utf-8"))
    document["complete"] = False
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StateIntegrityError):
        load_execution_state(path)


def test_retries_are_bounded_and_committed_once(tmp_path: Path) -> None:
    attempts = 0

    def flaky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient")

    result = PhaseRunner(tmp_path / "state.json", [("phase:1", flaky)], max_retries=2).run_all()
    assert result.complete
    assert attempts == 3
    assert result.committed_steps == ("phase:1",)
