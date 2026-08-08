from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from denser.core.models import TileAddress
from denser.wsi.color import ColorPolicy, canonicalize_rgb


class SlideReader(Protocol):
    level_dimensions: tuple[tuple[int, int], ...]
    codec_metadata: dict[str, str]

    def read_level0_region(self, address: TileAddress) -> np.ndarray: ...


@dataclass(slots=True)
class _PillowFixtureReader:
    path: Path
    level_dimensions: tuple[tuple[int, int], ...]
    codec_metadata: dict[str, str]
    source_icc: bytes | None

    def read_level0_region(self, address: TileAddress) -> np.ndarray:
        if address.level != 0:
            raise ValueError("read_level0_region only accepts level zero addresses")
        canvas = Image.new("RGBA", (address.width, address.height), (255, 255, 255, 0))
        with Image.open(self.path) as source:
            rgba = source.convert("RGBA")
            right = min(address.x + address.width, rgba.width)
            bottom = min(address.y + address.height, rgba.height)
            if right > address.x and bottom > address.y:
                crop = rgba.crop((address.x, address.y, right, bottom))
                canvas.paste(crop, (0, 0))
        return canonicalize_rgb(
            np.asarray(canvas, dtype=np.uint8), self.source_icc, ColorPolicy()
        ).rgb


class _OpenSlideReader:
    def __init__(self, path: Path) -> None:
        try:
            import openslide
        except (ImportError, OSError) as error:
            raise RuntimeError("OpenSlide Python bindings are unavailable") from error
        self._slide = openslide.OpenSlide(str(path))
        self.level_dimensions = tuple(
            (int(width), int(height)) for width, height in self._slide.level_dimensions
        )
        self.codec_metadata = {
            "backend": "openslide",
            "vendor": self._slide.properties.get("openslide.vendor", "unknown"),
            "level_count": str(self._slide.level_count),
        }
        declared_stain = self._slide.properties.get("denser.stain", "H&E")
        if declared_stain.casefold() not in {"h&e", "he", "hematoxylin and eosin"}:
            self._slide.close()
            raise ValueError("slide is outside the declared H&E scope")
        color_profile = getattr(self._slide, "color_profile", None)
        self._source_icc = color_profile.tobytes() if color_profile is not None else None

    def read_level0_region(self, address: TileAddress) -> np.ndarray:
        if address.level != 0:
            raise ValueError("read_level0_region only accepts level zero addresses")
        region = self._slide.read_region(
            (address.x, address.y), 0, (address.width, address.height)
        )
        return canonicalize_rgb(
            np.asarray(region, dtype=np.uint8), self._source_icc, ColorPolicy()
        ).rgb


def open_slide(path: Path) -> SlideReader:
    resolved = path.resolve(strict=True)
    if resolved.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        with Image.open(resolved) as image:
            dimensions = ((image.width, image.height),)
            icc = image.info.get("icc_profile")
            source_icc = icc if isinstance(icc, bytes) else None
        return _PillowFixtureReader(
            resolved,
            dimensions,
            {"backend": "pillow-fixture", "level_count": "1"},
            source_icc,
        )
    return _OpenSlideReader(resolved)
