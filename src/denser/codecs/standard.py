from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from denser.codecs.avif import AvifCodec
from denser.codecs.base import EncodedCandidate
from denser.codecs.jpeg import JpegCodec
from denser.codecs.jpeg2000 import Jpeg2000Codec
from denser.codecs.jpegxl import JpegXlCodec


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
    return [codec.encode(rgb) for codec in codecs]
