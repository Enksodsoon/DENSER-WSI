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


def test_byte_stable_codecs_use_three_threads_under_two_process_limit(
    tmp_path: Path,
) -> None:
    jpegxl_encode = JpegXlCodec(0.5).encode_command(
        tmp_path / "in.ppm", tmp_path / "out.jxl"
    )
    jpegxl_decode = JpegXlCodec(0.5).decode_command(
        tmp_path / "out.jxl", tmp_path / "decoded.ppm"
    )
    jpeg2000_encode = Jpeg2000Codec(4).encode_command(
        tmp_path / "in.ppm", tmp_path / "out.jp2"
    )
    jpeg2000_decode = Jpeg2000Codec(4).decode_command(
        tmp_path / "out.jp2", tmp_path / "decoded.ppm"
    )
    assert "--num_threads=3" in jpegxl_encode
    assert "--num_threads=3" in jpegxl_decode
    assert jpeg2000_encode[-2:] == ["-threads", "3"]
    assert jpeg2000_decode[-2:] == ["-threads", "3"]
    avif_encode = AvifCodec(90).encode_command(
        tmp_path / "in.png", tmp_path / "out.avif"
    )
    assert avif_encode[avif_encode.index("--jobs") + 1] == "1"
