from __future__ import annotations

import numpy as np
import pytest

from denser.codecs.lossless import LosslessIntegrityError, SharedLosslessCodec


@pytest.mark.parametrize("shape", [(1, 1, 3), (3, 7, 3), (16, 16, 3), (31, 9, 3)])
def test_shared_fallback_is_pixel_exact(shape: tuple[int, int, int]) -> None:
    rgb = np.random.default_rng(sum(shape)).integers(0, 256, shape, dtype=np.uint8)
    encoded = SharedLosslessCodec().encode(rgb)
    decoded = SharedLosslessCodec().decode(encoded.payload, rgb.shape)
    np.testing.assert_array_equal(decoded, rgb)


def test_shared_fallback_is_byte_deterministic() -> None:
    rgb = np.arange(12 * 13 * 3, dtype=np.uint8).reshape((12, 13, 3))
    codec = SharedLosslessCodec()
    assert codec.encode(rgb).payload == codec.encode(rgb.copy()).payload


def test_shared_fallback_rejects_shape_mismatch() -> None:
    rgb = np.zeros((2, 3, 3), dtype=np.uint8)
    encoded = SharedLosslessCodec().encode(rgb)
    with pytest.raises(LosslessIntegrityError, match="shape"):
        SharedLosslessCodec().decode(encoded.payload, (3, 2, 3))


def test_shared_fallback_rejects_corruption() -> None:
    encoded = SharedLosslessCodec().encode(np.zeros((4, 4, 3), dtype=np.uint8))
    damaged = bytearray(encoded.payload)
    damaged[-1] ^= 1
    with pytest.raises(LosslessIntegrityError):
        SharedLosslessCodec().decode(bytes(damaged), (4, 4, 3))


def test_shared_fallback_rejects_non_rgb_input() -> None:
    with pytest.raises(ValueError, match="uint8 RGB"):
        SharedLosslessCodec().encode(np.zeros((4, 4), dtype=np.uint8))
