from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from threading import BoundedSemaphore

import numpy as np
from PIL import Image

from denser.codecs.base import EncodedCandidate
from denser.core.models import ByteBreakdown
from denser.toolchain.probe import ToolSpec, probe_tool


class CodecExecutionError(RuntimeError):
    """An isolated native codec process violated its execution contract."""


_NATIVE_CODEC_PROCESS_SLOTS = BoundedSemaphore(2)


class SubprocessCodec(ABC):
    codec_id: str
    profile_id: str
    encoder_executable: str
    decoder_executable: str
    input_extension: str
    payload_extension: str
    decoded_extension: str
    encoder_version_args: tuple[str, ...] = ("--version",)
    timeout_seconds: float = 60.0
    max_input_bytes: int = 512 * 1024 * 1024
    max_output_bytes: int = 512 * 1024 * 1024

    @abstractmethod
    def encode_command(self, input_path: Path, output_path: Path) -> list[str]: ...

    @abstractmethod
    def decode_command(self, input_path: Path, output_path: Path) -> list[str]: ...

    def _run(self, command: list[str], root: Path) -> None:
        executable = shutil.which(command[0])
        if executable is None:
            raise CodecExecutionError(f"executable_not_found:{command[0]}")
        safe_command = [executable, *command[1:]]
        try:
            with _NATIVE_CODEC_PROCESS_SLOTS:
                completed = subprocess.run(
                    safe_command,
                    shell=False,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=root,
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CodecExecutionError(f"codec_process_failed:{command[0]}") from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-1000:].replace(
                str(root), "<isolated>"
            )
            raise CodecExecutionError(
                f"codec_exit_{completed.returncode}:{command[0]}:{detail}"
            )

    def _attestation(self) -> tuple[tuple[str, str], ...]:
        record = probe_tool(
            ToolSpec(self.encoder_executable, self.encoder_version_args)
        )
        if not record.available or record.executable_sha256 is None or record.version is None:
            raise CodecExecutionError(
                f"encoder_attestation_failed:{self.encoder_executable}:{record.error_code}"
            )
        return (
            ("encoder", self.encoder_executable),
            ("encoder_version", ".".join(str(value) for value in record.version)),
            ("encoder_sha256", record.executable_sha256),
        )

    @staticmethod
    def _validate_rgb(rgb: np.ndarray) -> np.ndarray:
        pixels = np.asarray(rgb)
        if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
            raise ValueError("codec input must be uint8 RGB")
        return np.ascontiguousarray(pixels)

    def encode(self, rgb: np.ndarray) -> EncodedCandidate:
        pixels = self._validate_rgb(rgb)
        if pixels.nbytes > self.max_input_bytes:
            raise CodecExecutionError("codec input exceeds configured size limit")
        with tempfile.TemporaryDirectory(prefix="denser-codec-") as temporary:
            root = Path(temporary)
            input_path = root / f"input.{self.input_extension}"
            output_path = root / f"output.{self.payload_extension}"
            image_format = "PNG" if self.input_extension == "png" else "PPM"
            Image.fromarray(pixels, mode="RGB").save(input_path, format=image_format)
            self._run(self.encode_command(input_path, output_path), root)
            if not output_path.is_file():
                raise CodecExecutionError("codec produced no output")
            if output_path.stat().st_size > self.max_output_bytes:
                raise CodecExecutionError("codec output exceeds configured size limit")
            payload = output_path.read_bytes()
        return EncodedCandidate(
            self.codec_id,
            self.profile_id,
            payload,
            ByteBreakdown(payload=len(payload)),
            self._attestation(),
        )

    def decode(self, payload: bytes, shape: tuple[int, int, int]) -> np.ndarray:
        if len(payload) > self.max_input_bytes:
            raise CodecExecutionError("codec payload exceeds configured size limit")
        with tempfile.TemporaryDirectory(prefix="denser-codec-") as temporary:
            root = Path(temporary)
            input_path = root / f"input.{self.payload_extension}"
            output_path = root / f"decoded.{self.decoded_extension}"
            input_path.write_bytes(payload)
            self._run(self.decode_command(input_path, output_path), root)
            if not output_path.is_file() or output_path.stat().st_size > self.max_output_bytes:
                raise CodecExecutionError("decoder output is absent or exceeds size limit")
            with Image.open(output_path) as image:
                decoded = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
        if decoded.shape != shape or decoded.dtype != np.uint8:
            raise CodecExecutionError("decoded shape or dtype violates codec contract")
        return decoded
