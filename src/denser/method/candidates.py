from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.core.models import ByteBreakdown
from denser.method.quantize import sensitivity_weighted_steps, uniform_quantize
from denser.method.transform import forward_transform, inverse_transform


MAGIC = b"DNQ1"
HEADER = struct.Struct(">4sHHHHBBfII32s")
BASIS_ID = "block-dct8-rgb-v1"
ENTROPY_MODEL_ID = "int32-zlib-fixed-v1"


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    quantization_steps: tuple[float, ...]
    trust_region_ratio: float = 4.0
    basis_id: str = BASIS_ID
    entropy_model_id: str = ENTROPY_MODEL_ID

    def __post_init__(self) -> None:
        if not self.quantization_steps or any(
            not np.isfinite(step) or step <= 0 for step in self.quantization_steps
        ):
            raise ValueError("candidate ladder requires positive finite steps")
        if self.trust_region_ratio < 1:
            raise ValueError("trust-region ratio must be at least one")
        if self.basis_id != BASIS_ID or self.entropy_model_id != ENTROPY_MODEL_ID:
            raise ValueError("candidate coder identity is frozen")


def _compress(raw: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_FIXED)
    return compressor.compress(raw) + compressor.flush(zlib.Z_FINISH)


def _packet(
    rgb: np.ndarray,
    coefficients: np.ndarray,
    base_step: float,
    step_map: np.ndarray | None,
) -> bytes:
    height, width, channels = rgb.shape
    padded_height, padded_width, _ = coefficients.shape
    if step_map is None:
        mode = 0
        steps_raw = b""
        quantized = uniform_quantize(coefficients, base_step)
        step_count = 0
    else:
        mode = 1
        steps = np.asarray(step_map, dtype=">f4")
        steps_raw = steps.tobytes(order="C")
        quantized = np.rint(coefficients / step_map).astype(np.int32)
        step_count = coefficients.size
    quantized_raw = quantized.astype(">i4", copy=False).tobytes(order="C")
    raw = steps_raw + quantized_raw
    compressed = _compress(raw)
    header = HEADER.pack(
        MAGIC,
        height,
        width,
        padded_height,
        padded_width,
        channels,
        mode,
        base_step,
        step_count,
        len(compressed),
        hashlib.sha256(raw).digest(),
    )
    return header + compressed


def _candidate(payload: bytes, profile_id: str, profile: CandidateProfile) -> EncodedCandidate:
    return EncodedCandidate(
        codec_id="denser-transform",
        profile_id=profile_id,
        payload=payload,
        breakdown=ByteBreakdown(payload=len(payload)),
        basis_id=profile.basis_id,
        entropy_model_id=profile.entropy_model_id,
    )


def build_uniform_candidates(
    rgb: np.ndarray, profile: CandidateProfile
) -> list[EncodedCandidate]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    coefficients, _ = forward_transform(pixels)
    return [
        _candidate(
            _packet(pixels, coefficients, step, None),
            f"uniform-q{step:g}",
            profile,
        )
        for step in profile.quantization_steps
    ]


def build_denser_candidates(
    rgb: np.ndarray, sensitivity: np.ndarray, profile: CandidateProfile
) -> list[EncodedCandidate]:
    pixels = np.asarray(rgb, dtype=np.uint8)
    sensitivity_values = np.asarray(sensitivity, dtype=np.float64)
    if sensitivity_values.shape != pixels.shape:
        raise ValueError("sensitivity field must match RGB shape")
    coefficients, _ = forward_transform(pixels)
    sensitivity_coefficients, _ = forward_transform(np.abs(sensitivity_values))
    weights = np.abs(sensitivity_coefficients) + 1e-12
    return [
        _candidate(
            _packet(
                pixels,
                coefficients,
                step,
                sensitivity_weighted_steps(weights, step, profile.trust_region_ratio),
            ),
            f"denser-q{step:g}",
            profile,
        )
        for step in profile.quantization_steps
    ]


def decode_transform_candidate(payload: bytes) -> np.ndarray:
    if len(payload) < HEADER.size:
        raise ValueError("transform packet is truncated")
    (
        magic,
        height,
        width,
        padded_height,
        padded_width,
        channels,
        mode,
        base_step,
        step_count,
        compressed_length,
        digest,
    ) = HEADER.unpack_from(payload)
    if magic != MAGIC or channels != 3 or mode not in (0, 1):
        raise ValueError("transform packet header is invalid")
    compressed = payload[HEADER.size:]
    if len(compressed) != compressed_length:
        raise ValueError("transform packet length mismatch")
    try:
        decompressor = zlib.decompressobj(-15)
        raw = decompressor.decompress(compressed) + decompressor.flush()
    except zlib.error as error:
        raise ValueError("transform packet compression is invalid") from error
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("transform packet stream is noncanonical")
    if hashlib.sha256(raw).digest() != digest:
        raise ValueError("transform packet digest mismatch")
    coefficient_count = padded_height * padded_width * channels
    if mode == 0:
        if step_count != 0 or len(raw) != coefficient_count * 4:
            raise ValueError("uniform transform packet layout is invalid")
        steps: float | np.ndarray = float(base_step)
        quantized_raw = raw
    else:
        if step_count != coefficient_count or len(raw) != coefficient_count * 8:
            raise ValueError("DENSER transform packet layout is invalid")
        steps = np.frombuffer(raw[: coefficient_count * 4], dtype=">f4").astype(np.float64).reshape(
            (padded_height, padded_width, channels)
        )
        quantized_raw = raw[coefficient_count * 4 :]
    quantized = np.frombuffer(quantized_raw, dtype=">i4").astype(np.float64).reshape(
        (padded_height, padded_width, channels)
    )
    coefficients = quantized * steps
    return inverse_transform(coefficients, (height, width))
