from __future__ import annotations

import shutil

import numpy as np
import pytest

from denser.codecs.avif import AvifCodec
from denser.codecs.jpeg import JpegCodec
from denser.codecs.jpeg2000 import Jpeg2000Codec
from denser.codecs.jpegxl import JpegXlCodec


@pytest.mark.parametrize(
    "codec",
    [JpegCodec(85), Jpeg2000Codec(8), JpegXlCodec(1.5), AvifCodec(70)],
)
def test_available_native_codec_round_trip_has_exact_contract(codec) -> None:  # type: ignore[no-untyped-def]
    if shutil.which(codec.encoder_executable) is None or shutil.which(codec.decoder_executable) is None:
        pytest.skip(f"structured_skip:executable_not_found:{codec.codec_id}")
    y, x = np.mgrid[:16, :17]
    rgb = np.stack(((x * 13) % 256, (y * 17) % 256, ((x + y) * 7) % 256), axis=2).astype(np.uint8)
    encoded = codec.encode(rgb)
    decoded = codec.decode(encoded.payload, rgb.shape)
    assert decoded.shape == rgb.shape
    assert decoded.dtype == np.uint8
    assert encoded.attestation
