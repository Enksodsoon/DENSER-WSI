from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import denser.codecs.standard as standard
import denser.codecs.subprocess_codec as subprocess_codec
from denser.codecs.base import EncodedCandidate
from denser.codecs.standard import StandardLadder, build_standard_candidates
from denser.core.models import ByteBreakdown


def test_standard_candidates_respect_two_subprocess_concurrency_cap(monkeypatch) -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()

    class SlowCodec:
        def __init__(self, value: object) -> None:
            self.value = value

        def encode(self, rgb: np.ndarray) -> EncodedCandidate:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            payload = str(self.value).encode("ascii")
            return EncodedCandidate("slow", str(self.value), payload, ByteBreakdown(payload=len(payload)))

    for name in ("JpegCodec", "Jpeg2000Codec", "JpegXlCodec", "AvifCodec"):
        monkeypatch.setattr(standard, name, SlowCodec)
    ladder = StandardLadder((70,), (4,), (0.5,), (60,))
    result = build_standard_candidates(np.zeros((8, 8, 3), dtype=np.uint8), ladder)
    assert maximum == 2
    assert [item.profile_id for item in result] == ["70", "4", "0.5", "60"]


def test_subprocess_cap_is_global_across_concurrent_tiles(monkeypatch) -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()

    class SlowCodec:
        def __init__(self, value: object) -> None:
            self.value = value

        def encode(self, rgb: np.ndarray) -> EncodedCandidate:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return EncodedCandidate("slow", "profile", b"x", ByteBreakdown(payload=1))

    for name in ("JpegCodec", "Jpeg2000Codec", "JpegXlCodec", "AvifCodec"):
        monkeypatch.setattr(standard, name, SlowCodec)
    ladder = StandardLadder((70,), (4,), (0.5,), (60,))
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _index: build_standard_candidates(rgb, ladder), range(3)))
    assert maximum == 2


def test_native_codec_runner_caps_parallel_encode_and_decode_processes(
    monkeypatch, tmp_path
) -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return Completed()

    monkeypatch.setattr(subprocess_codec.shutil, "which", lambda executable: executable)
    monkeypatch.setattr(subprocess_codec.subprocess, "run", fake_run)
    codec = standard.JpegCodec(90)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _index: codec._run(["codec"], tmp_path), range(6)))
    assert maximum == 2
