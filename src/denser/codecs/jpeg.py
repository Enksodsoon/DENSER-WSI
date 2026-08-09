from __future__ import annotations

from pathlib import Path

from denser.codecs.subprocess_codec import SubprocessCodec


class JpegCodec(SubprocessCodec):
    codec_id = "jpeg"
    encoder_executable = "cjpeg"
    decoder_executable = "djpeg"
    input_extension = "ppm"
    payload_extension = "jpg"
    decoded_extension = "ppm"
    encoder_version_args = ("-version",)

    def __init__(self, quality: int) -> None:
        if not 1 <= quality <= 100:
            raise ValueError("JPEG quality must be between 1 and 100")
        self.quality = quality
        self.profile_id = f"jpeg-q{quality}-444-opt"

    def encode_command(self, input_path: Path, output_path: Path) -> list[str]:
        return [
            self.encoder_executable,
            "-quality",
            str(self.quality),
            "-sample",
            "1x1",
            "-optimize",
            "-outfile",
            str(output_path),
            str(input_path),
        ]

    def decode_command(self, input_path: Path, output_path: Path) -> list[str]:
        return [
            self.decoder_executable,
            "-ppm",
            "-outfile",
            str(output_path),
            str(input_path),
        ]
