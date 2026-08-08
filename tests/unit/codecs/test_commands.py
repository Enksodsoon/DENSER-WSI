from __future__ import annotations

from pathlib import Path

import pytest

from denser.codecs.avif import AvifCodec
from denser.codecs.jpeg import JpegCodec
from denser.codecs.jpeg2000 import Jpeg2000Codec
from denser.codecs.jpegxl import JpegXlCodec


def test_jpeg_command_forces_444_and_disables_metadata(tmp_path: Path) -> None:
    command = JpegCodec(quality=75).encode_command(
        tmp_path / "input image.ppm", tmp_path / "output.jpg"
    )
    assert command[:5] == ["cjpeg", "-quality", "75", "-sample", "1x1"]
    assert "-outfile" in command
    assert str(tmp_path / "input image.ppm") in command


@pytest.mark.parametrize(
    ("codec", "encoder", "decoder"),
    [
        (JpegCodec(80), "cjpeg", "djpeg"),
        (Jpeg2000Codec(8), "opj_compress", "opj_decompress"),
        (JpegXlCodec(1.5), "cjxl", "djxl"),
        (AvifCodec(70), "avifenc", "avifdec"),
    ],
)
def test_commands_are_argument_arrays_without_shell_metacharacters(
    tmp_path: Path, codec, encoder: str, decoder: str  # type: ignore[no-untyped-def]
) -> None:
    input_path = tmp_path / f"in.{codec.input_extension}"
    payload_path = tmp_path / f"out.{codec.payload_extension}"
    decoded_path = tmp_path / f"decoded.{codec.decoded_extension}"
    encode = codec.encode_command(input_path, payload_path)
    decode = codec.decode_command(payload_path, decoded_path)
    assert encode[0] == encoder
    assert decode[0] == decoder
    assert all(isinstance(part, str) and "\n" not in part for part in encode + decode)


def test_invalid_profiles_are_rejected() -> None:
    with pytest.raises(ValueError):
        JpegCodec(0)
    with pytest.raises(ValueError):
        Jpeg2000Codec(0)
    with pytest.raises(ValueError):
        JpegXlCodec(-1)
    with pytest.raises(ValueError):
        AvifCodec(101)
