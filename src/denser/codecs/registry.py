from __future__ import annotations

from collections.abc import Callable
import re

import numpy as np

from denser.codecs.base import EncodedCandidate


Decoder = Callable[[bytes, bytes, tuple[int, int, int], str], np.ndarray]


class UnknownCodecError(ValueError):
    """A packet requested a codec outside the frozen registry."""


class CodecRegistry:
    def __init__(self) -> None:
        self._decoders: dict[str, Decoder] = {}

    def register(self, codec_id: str, decoder: Decoder) -> None:
        if not codec_id or codec_id in self._decoders:
            raise ValueError("codec identity is empty or already registered")
        self._decoders[codec_id] = decoder

    def decode(self, candidate: EncodedCandidate, shape: tuple[int, int, int]) -> np.ndarray:
        try:
            decoder = self._decoders[candidate.codec_id]
        except KeyError as error:
            raise UnknownCodecError(f"unknown codec: {candidate.codec_id}") from error
        decoded = np.asarray(
            decoder(candidate.payload, candidate.allocation_map, shape, candidate.profile_id)
        )
        if decoded.dtype != np.uint8 or decoded.shape != shape:
            raise ValueError("registered codec returned an invalid dtype or shape")
        return decoded


def _profile_value(profile: str, pattern: str, cast):  # type: ignore[no-untyped-def]
    match = re.fullmatch(pattern, profile)
    if match is None:
        raise ValueError(f"codec profile is invalid: {profile}")
    return cast(match.group(1))


def build_default_registry() -> CodecRegistry:
    from denser.codecs.avif import AvifCodec
    from denser.codecs.jpeg import JpegCodec
    from denser.codecs.jpeg2000 import Jpeg2000Codec
    from denser.codecs.jpegxl import JpegXlCodec
    from denser.codecs.lossless import SharedLosslessCodec
    from denser.codecs.quadtree import decode_jpegxl_quadtree_candidate
    from denser.method.candidates import decode_candidate

    registry = CodecRegistry()
    registry.register(
        SharedLosslessCodec.codec_id,
        lambda payload, allocation, shape, profile: SharedLosslessCodec().decode(payload, shape),
    )
    registry.register(
        "denser-transform",
        lambda payload, allocation, shape, profile: decode_candidate(payload, allocation),
    )
    registry.register(
        "denser-eam-dct-v2",
        lambda payload, allocation, shape, profile: decode_candidate(payload, allocation),
    )
    registry.register(
        "denser-quadtree-jxl-v2",
        lambda payload, allocation, shape, profile: decode_jpegxl_quadtree_candidate(
            payload, allocation
        ),
    )
    registry.register(
        JpegCodec.codec_id,
        lambda payload, allocation, shape, profile: JpegCodec(
            _profile_value(profile, r"jpeg-q(\d+)-444-opt", int)
        ).decode(payload, shape),
    )
    registry.register(
        Jpeg2000Codec.codec_id,
        lambda payload, allocation, shape, profile: Jpeg2000Codec(
            _profile_value(profile, r"jpeg2000-r(\d+)", int)
        ).decode(payload, shape),
    )
    registry.register(
        JpegXlCodec.codec_id,
        lambda payload, allocation, shape, profile: JpegXlCodec(
            _profile_value(profile, r"jpegxl-d([0-9]+(?:\.[0-9]+)?)-e7", float)
        ).decode(payload, shape),
    )
    registry.register(
        AvifCodec.codec_id,
        lambda payload, allocation, shape, profile: AvifCodec(
            _profile_value(profile, r"avif-q(\d+)-s6", int)
        ).decode(payload, shape),
    )
    return registry
