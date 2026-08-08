from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import BoundedSemaphore

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


def build_standard_candidates(
    rgb: np.ndarray, ladder: StandardLadder
) -> list[EncodedCandidate]:
    codecs = [JpegCodec(value) for value in ladder.jpeg_qualities]
    codecs.extend(Jpeg2000Codec(value) for value in ladder.jpeg2000_ratios)
    codecs.extend(JpegXlCodec(value) for value in ladder.jpegxl_distances)
    codecs.extend(AvifCodec(value) for value in ladder.avif_qualities)
    with ThreadPoolExecutor(max_workers=min(2, len(codecs))) as pool:
        return list(pool.map(lambda codec: _encode_with_global_limit(codec, rgb), codecs))
