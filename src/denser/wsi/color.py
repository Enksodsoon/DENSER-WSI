from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageCms


@dataclass(frozen=True, slots=True)
class ColorPolicy:
    require_valid: bool = False
    output_space: str = "sRGB IEC61966-2.1"


@dataclass(frozen=True, slots=True)
class CanonicalRgb:
    rgb: np.ndarray
    status: str
    output_space: str
    source_icc_sha256: str | None


def _without_alpha(pixels: np.ndarray) -> np.ndarray:
    if pixels.shape[2] == 3:
        return pixels.copy()
    alpha = pixels[:, :, 3:4].astype(np.uint16)
    foreground = pixels[:, :, :3].astype(np.uint16)
    composited = (foreground * alpha + 255 * (255 - alpha) + 127) // 255
    return composited.astype(np.uint8)


def canonicalize_rgb(
    rgb: np.ndarray, source_icc: bytes | None, policy: ColorPolicy
) -> CanonicalRgb:
    pixels = np.asarray(rgb)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
        raise ValueError("decoded pixels must be uint8 RGB or RGBA")
    canonical = _without_alpha(pixels)
    if source_icc is None:
        return CanonicalRgb(canonical, "profile_missing", policy.output_space, None)
    source_hash = hashlib.sha256(source_icc).hexdigest()
    try:
        source_profile = ImageCms.ImageCmsProfile(BytesIO(source_icc))
        destination_profile = ImageCms.createProfile("sRGB")
        image = Image.fromarray(canonical, mode="RGB")
        converted = ImageCms.profileToProfile(
            image,
            source_profile,
            destination_profile,
            renderingIntent=ImageCms.Intent.PERCEPTUAL,
            outputMode="RGB",
        )
        output = np.asarray(converted, dtype=np.uint8).copy()
    except (OSError, ValueError, ImageCms.PyCMSError) as error:
        if policy.require_valid:
            raise ValueError("source ICC profile is invalid") from error
        return CanonicalRgb(canonical, "profile_invalid", policy.output_space, source_hash)
    return CanonicalRgb(output, "profile_converted", policy.output_space, source_hash)
