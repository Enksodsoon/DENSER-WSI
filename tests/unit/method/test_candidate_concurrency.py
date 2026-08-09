from __future__ import annotations

import threading
import time

import numpy as np

import denser.method.candidates as candidates
from denser.method.candidates import CandidateProfile, build_uniform_candidates


def test_candidate_packets_use_at_most_two_concurrent_workers(monkeypatch) -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()

    def slow_packet(rgb, coefficients, base_step, step_map):  # type: ignore[no-untyped-def]
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return bytes([int(base_step)])

    monkeypatch.setattr(candidates, "_packet", slow_packet)
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    result = build_uniform_candidates(rgb, CandidateProfile((1.0, 2.0, 3.0, 4.0)))
    assert maximum == 2
    assert [item.payload for item in result] == [b"\x01", b"\x02", b"\x03", b"\x04"]
