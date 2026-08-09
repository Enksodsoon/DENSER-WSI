from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from denser.codecs.subprocess_codec import SubprocessCodec


class Jpeg2000Codec(SubprocessCodec):
    codec_id = "jpeg2000"
    encoder_executable = "opj_compress"
    decoder_executable = "opj_decompress"
    input_extension = "ppm"
    payload_extension = "jp2"
    decoded_extension = "ppm"
    encoder_version_args = ("-h",)

    def __init__(self, ratio: int) -> None:
        if ratio <= 0:
            raise ValueError("JPEG 2000 ratio must be positive")
        self.ratio = ratio
        self.profile_id = f"jpeg2000-r{ratio}"

    def encode_command(self, input_path: Path, output_path: Path) -> list[str]:
        resolutions = 6
        if input_path.is_file():
            with Image.open(input_path) as image:
                resolutions = max(1, min(6, int(math.log2(min(image.size))) + 1))
        return [
            self.encoder_executable,
            "-i",
            str(input_path),
            "-o",
            str(output_path),
            "-r",
            str(self.ratio),
            "-n",
            str(resolutions),
            "-threads",
            "3",
        ]

    def decode_command(self, input_path: Path, output_path: Path) -> list[str]:
        return [
            self.decoder_executable,
            "-i",
            str(input_path),
            "-o",
            str(output_path),
            "-threads",
            "3",
        ]
