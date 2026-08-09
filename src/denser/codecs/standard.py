from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import BoundedSemaphore
import re

import numpy as np

from denser.codecs.avif import AvifCodec
from denser.codecs.base import EncodedCandidate
from denser.codecs.jpeg import JpegCodec
from denser.codecs.jpeg2000 import Jpeg2000Codec
from denser.codecs.jpegxl import JpegXlCodec


_SUBPROCESS_SLOTS = BoundedSemaphore(2)


def _encode_with_global_limit(codec, rgb: np.ndarray) -> EncodedCandidate:  # type: ignore[no-untyped-def]
    with _SUBPROCESS_SLOTS:
        return codec.encode(rgb)


@dataclass(frozen=True, slots=True)
class StandardLadder:
    jpeg_qualities: tuple[int, ...] = (70, 80, 90)
    jpeg2000_ratios: tuple[int, ...] = (4, 8, 16)
    jpegxl_distances: tuple[float, ...] = (0.5, 1.0, 2.0)
    avif_qualities: tuple[int, ...] = (60, 75, 90)


def ladder_from_profile_ids(profile_ids: tuple[str, ...]) -> StandardLadder:
    if not profile_ids:
        raise ValueError("standard routing requires at least one profile")
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("standard routing contains a duplicate profile")
    jpeg: list[int] = []
    jpeg2000: list[int] = []
    jpegxl: list[float] = []
    avif: list[int] = []
    patterns = (
        (re.compile(r"jpeg-q(\d+)-444-opt"), jpeg, int),
        (re.compile(r"jpeg2000-r(\d+)"), jpeg2000, int),
        (re.compile(r"jpegxl-d([0-9]+(?:\.[0-9]+)?)-e7"), jpegxl, float),
        (re.compile(r"avif-q(\d+)-s6"), avif, int),
    )
    for profile_id in profile_ids:
        for pattern, destination, cast in patterns:
            match = pattern.fullmatch(profile_id)
            if match is not None:
                destination.append(cast(match.group(1)))
                break
        else:
            raise ValueError(f"unknown standard profile in routing: {profile_id}")
    return StandardLadder(
        tuple(sorted(jpeg)),
        tuple(sorted(jpeg2000)),
        tuple(sorted(jpegxl)),
        tuple(sorted(avif)),
    )


def build_standard_candidates(
    rgb: np.ndarray, ladder: StandardLadder
) -> list[EncodedCandidate]:
    codecs = [JpegCodec(value) for value in ladder.jpeg_qualities]
    codecs.extend(Jpeg2000Codec(value) for value in ladder.jpeg2000_ratios)
    codecs.extend(JpegXlCodec(value) for value in ladder.jpegxl_distances)
    codecs.extend(AvifCodec(value) for value in ladder.avif_qualities)
    with ThreadPoolExecutor(max_workers=min(2, len(codecs))) as pool:
        return list(pool.map(lambda codec: _encode_with_global_limit(codec, rgb), codecs))
