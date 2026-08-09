from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from denser.orchestration.state import ExecutionState, load_execution_state, save_execution_state


class SimulatedCrash(RuntimeError):
    """Test-only crash injected after work and before its atomic commit."""


@dataclass(frozen=True, slots=True)
class CompletionState:
    complete: bool
    committed_steps: tuple[str, ...]
    completed_phases: tuple[str, ...]
    repeated_steps: tuple[str, ...]


class PhaseRunner:
    def __init__(
        self,
        state_path: Path,
        steps: Iterable[tuple[str, Callable[[], None]]],
        *,
        max_retries: int = 2,
        crash_after: str | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.state_path = Path(state_path)
        self.steps = tuple(steps)
        identifiers = [identifier for identifier, _function in self.steps]
        if len(set(identifiers)) != len(identifiers) or any(":" not in item for item in identifiers):
            raise ValueError("step identifiers must be unique phase:step values")
        self.max_retries = max_retries
        self.crash_after = crash_after
        self._crash_injected = False

    def _load_or_create(self) -> ExecutionState:
        if self.state_path.exists():
            return load_execution_state(self.state_path)
        state = ExecutionState()
        save_execution_state(self.state_path, state)
        return state

    def _completion(self, state: ExecutionState) -> CompletionState:
        return CompletionState(
            state.complete,
            tuple(state.committed_steps),
            tuple(state.completed_phases),
            tuple(state.repeated_steps),
        )

    def run_all(self) -> CompletionState:
        state = self._load_or_create()
        if state.in_progress_step is not None and state.in_progress_step not in state.repeated_steps:
            state.repeated_steps.append(state.in_progress_step)
            save_execution_state(self.state_path, state)
        known = {identifier for identifier, _function in self.steps}
        if any(identifier not in known for identifier in state.committed_steps):
            raise RuntimeError("execution state contains steps absent from this phase plan")
        for identifier, function in self.steps:
            if identifier in state.committed_steps:
                continue
            state.in_progress_step = identifier
            save_execution_state(self.state_path, state)
            prior_attempts = state.attempts.get(identifier, 0)
            while True:
                state.attempts[identifier] = prior_attempts + 1
                save_execution_state(self.state_path, state)
                try:
                    function()
                    break
                except Exception:
                    prior_attempts += 1
                    if prior_attempts > self.max_retries:
                        raise
            if identifier == self.crash_after and not self._crash_injected:
                self._crash_injected = True
                raise SimulatedCrash(f"simulated crash after {identifier}")
            state.committed_steps.append(identifier)
            state.in_progress_step = None
            phase = identifier.split(":", 1)[0]
            remaining_in_phase = [
                item for item, _fn in self.steps
                if item.startswith(f"{phase}:") and item not in state.committed_steps
            ]
            if not remaining_in_phase and phase not in state.completed_phases:
                state.completed_phases.append(phase)
            save_execution_state(self.state_path, state)
        state.complete = True
        save_execution_state(self.state_path, state)
        return self._completion(state)

    def resume(self) -> CompletionState:
        if not self.state_path.exists():
            raise FileNotFoundError("cannot resume without execution state")
        return self.run_all()
