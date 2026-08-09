from __future__ import annotations

import hashlib

import numpy as np
import pytest

from denser.codecs.source_segments import (
    DECODER_APERIO_JP2,
    DECODER_TIFF_JPEG,
    SourceSegmentAllocationV2,
    build_source_segment_candidate,
    decode_source_segment_candidate,
)


def allocation(payload: bytes = b"payload") -> SourceSegmentAllocationV2:
    return SourceSegmentAllocationV2(
        decoder_code=DECODER_TIFF_JPEG,
        compression_code=7,
        tile_width=240,
        tile_height=240,
        canvas_width=720,
        canvas_height=720,
        crop_x=32,
        crop_y=48,
        crop_width=512,
        crop_height=512,
        payload_sha256=hashlib.sha256(payload).digest(),
    )


def test_source_segment_allocation_is_canonical_and_rejects_corruption() -> None:
    encoded = allocation().encode()
    assert SourceSegmentAllocationV2.decode(encoded) == allocation()
    damaged = bytearray(encoded)
    damaged[-1] ^= 1
    with pytest.raises(ValueError):
        SourceSegmentAllocationV2.decode(bytes(damaged))
    with pytest.raises(ValueError):
        SourceSegmentAllocationV2(
            DECODER_APERIO_JP2,
            33003,
            240,
            240,
            480,
            480,
            0,
            0,
            512,
            512,
            hashlib.sha256(b"x").digest(),
        )


def test_source_segment_candidate_decodes_independently_and_binds_payload() -> None:
    canvas = np.arange(720 * 720 * 3, dtype=np.uint32).reshape(720, 720, 3)
    canvas = (canvas % 256).astype(np.uint8)
    payload = b"self-contained-tiff"
    metadata = allocation(payload)
    candidate = build_source_segment_candidate(payload, metadata)
    decoded = decode_source_segment_candidate(
        candidate.payload,
        candidate.allocation_map,
        (512, 512, 3),
        canvas_decoder=lambda stored, record: canvas,
    )
    np.testing.assert_array_equal(decoded, canvas[48:560, 32:544])
    assert candidate.complete_bytes == len(payload) + len(candidate.allocation_map)
    with pytest.raises(ValueError, match="digest"):
        decode_source_segment_candidate(
            payload + b"x",
            metadata.encode(),
            (512, 512, 3),
            canvas_decoder=lambda stored, record: canvas,
        )


def test_source_segment_decoder_rejects_wrong_canvas_or_shape() -> None:
    payload = b"payload"
    metadata = allocation(payload)
    with pytest.raises(ValueError, match="canvas"):
        decode_source_segment_candidate(
            payload,
            metadata.encode(),
            (512, 512, 3),
            canvas_decoder=lambda stored, record: np.zeros((10, 10, 3), dtype=np.uint8),
        )
    with pytest.raises(ValueError, match="shape"):
        decode_source_segment_candidate(
            payload,
            metadata.encode(),
            (256, 256, 3),
            canvas_decoder=lambda stored, record: np.zeros((720, 720, 3), dtype=np.uint8),
        )
