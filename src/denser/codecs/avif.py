from __future__ import annotations

from pathlib import Path

from denser.codecs.subprocess_codec import SubprocessCodec


class AvifCodec(SubprocessCodec):
    codec_id = "avif"
    encoder_executable = "avifenc"
    decoder_executable = "avifdec"
    input_extension = "png"
    payload_extension = "avif"
    decoded_extension = "png"

    def __init__(self, quality: int) -> None:
        if not 0 <= quality <= 100:
            raise ValueError("AVIF quality must be between 0 and 100")
        self.quality = quality
        self.profile_id = f"avif-q{quality}-s6"

    def encode_command(self, input_path: Path, output_path: Path) -> list[str]:
        return [
            self.encoder_executable,
            "--qcolor",
            str(self.quality),
            "--qalpha",
            str(self.quality),
            "--jobs",
            "1",
            "--speed",
            "6",
            str(input_path),
            str(output_path),
        ]

    def decode_command(self, input_path: Path, output_path: Path) -> list[str]:
        return [self.decoder_executable, str(input_path), str(output_path)]
