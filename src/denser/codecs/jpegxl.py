from __future__ import annotations

from pathlib import Path

from denser.codecs.subprocess_codec import SubprocessCodec


class JpegXlCodec(SubprocessCodec):
    codec_id = "jpegxl"
    encoder_executable = "cjxl"
    decoder_executable = "djxl"
    input_extension = "ppm"
    payload_extension = "jxl"
    decoded_extension = "ppm"

    def __init__(self, distance: float) -> None:
        if distance < 0:
            raise ValueError("JPEG XL distance cannot be negative")
        self.distance = distance
        self.profile_id = f"jpegxl-d{distance:g}-e7"

    def encode_command(self, input_path: Path, output_path: Path) -> list[str]:
        return [
            self.encoder_executable,
            str(input_path),
            str(output_path),
            f"--distance={self.distance:g}",
            "--effort=7",
            "--num_threads=3",
        ]

    def decode_command(self, input_path: Path, output_path: Path) -> list[str]:
        return [
            self.decoder_executable,
            str(input_path),
            str(output_path),
            "--num_threads=3",
        ]
