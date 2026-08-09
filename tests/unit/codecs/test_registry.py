from __future__ import annotations

import numpy as np
import pytest

from denser.codecs.base import EncodedCandidate
from denser.codecs.lossless import SharedLosslessCodec
from denser.codecs.registry import CodecRegistry, UnknownCodecError, build_default_registry
from denser.codecs.source_segments import (
    DECODER_TIFF_JPEG,
    SourceSegmentAllocationV2,
    build_source_segment_candidate,
)
from denser.core.models import ByteBreakdown
from denser.method.candidates import CandidateProfile, build_uniform_candidates


def test_registry_dispatches_by_codec_and_profile() -> None:
    registry = CodecRegistry()
    registry.register(
        "fixture",
        lambda payload, allocation, shape, profile: np.full(shape, int(profile), dtype=np.uint8),
    )
    candidate = EncodedCandidate("fixture", "7", b"payload", ByteBreakdown(payload=7))
    decoded = registry.decode(candidate, (2, 3, 3))
    assert np.array_equal(decoded, np.full((2, 3, 3), 7))


def test_registry_rejects_unknown_codec_and_wrong_decoder_shape() -> None:
    registry = CodecRegistry()
    candidate = EncodedCandidate("missing", "x", b"x", ByteBreakdown(payload=1))
    with pytest.raises(UnknownCodecError):
        registry.decode(candidate, (1, 1, 3))

    registry.register(
        "bad", lambda payload, allocation, shape, profile: np.zeros((1, 1), dtype=np.uint8)
    )
    candidate = EncodedCandidate("bad", "x", b"x", ByteBreakdown(payload=1))
    with pytest.raises(ValueError, match="shape"):
        registry.decode(candidate, (1, 1, 3))


def test_default_registry_decodes_fallback_and_transform_candidates() -> None:
    rgb = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    registry = build_default_registry()
    fallback = SharedLosslessCodec().encode(rgb)
    transform = build_uniform_candidates(rgb, CandidateProfile((1.0,)))[0]
    np.testing.assert_array_equal(registry.decode(fallback, rgb.shape), rgb)
    assert registry.decode(transform, rgb.shape).shape == rgb.shape


def test_default_registry_dispatches_self_contained_source_segment(monkeypatch) -> None:
    import hashlib
    import denser.codecs.source_segments as source_segments

    canvas = np.arange(16 * 16 * 3, dtype=np.uint8).reshape(16, 16, 3)
    payload = b"self-contained-tiff"
    metadata = SourceSegmentAllocationV2(
        DECODER_TIFF_JPEG,
        7,
        8,
        8,
        16,
        16,
        3,
        4,
        8,
        8,
        hashlib.sha256(payload).digest(),
    )
    candidate = build_source_segment_candidate(payload, metadata)
    monkeypatch.setattr(source_segments, "_decode_canvas", lambda stored, record: canvas)
    decoded = build_default_registry().decode(candidate, (8, 8, 3))
    np.testing.assert_array_equal(decoded, canvas[4:12, 3:11])
