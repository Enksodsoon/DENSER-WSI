from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Iterable

import numpy as np


_HEADER = struct.Struct(">4sII")
_SPAN = struct.Struct(">III")


@dataclass(frozen=True, slots=True)
class RepairFailure:
    x: int
    y: int
    width: int
    height: int
    image_width: int
    image_height: int

    def __post_init__(self) -> None:
        if min(self.x, self.y) < 0 or min(self.width, self.height) <= 0:
            raise ValueError("failure bounds must be non-negative and non-empty")
        if min(self.image_width, self.image_height) <= 0:
            raise ValueError("image dimensions must be positive")
        if self.x + self.width > self.image_width or self.y + self.height > self.image_height:
            raise ValueError("failure bounds exceed the image")

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class RepairMask:
    pixels: np.ndarray
    encoded: bytes

    def __post_init__(self) -> None:
        if self.pixels.dtype != np.bool_ or self.pixels.ndim != 2:
            raise ValueError("repair mask must be a two-dimensional boolean array")

    @property
    def pixel_count(self) -> int:
        return int(np.count_nonzero(self.pixels))

    @property
    def shape(self) -> tuple[int, int]:
        return self.pixels.shape


def _encode_spans(pixels: np.ndarray) -> bytes:
    height, width = pixels.shape
    spans: list[tuple[int, int, int]] = []
    for y in range(height):
        row = pixels[y]
        x = 0
        while x < width:
            if not row[x]:
                x += 1
                continue
            start = x
            while x < width and row[x]:
                x += 1
            spans.append((y, start, x - start))
    return b"".join(
        [_HEADER.pack(b"RMV1", height, width), struct.pack(">I", len(spans))]
        + [_SPAN.pack(*span) for span in spans]
    )


def decode_repair_mask(payload: bytes) -> RepairMask:
    minimum = _HEADER.size + 4
    if len(payload) < minimum:
        raise ValueError("repair mask is truncated")
    magic, height, width = _HEADER.unpack_from(payload)
    span_count = struct.unpack_from(">I", payload, _HEADER.size)[0]
    if magic != b"RMV1" or min(height, width) <= 0:
        raise ValueError("repair-mask header is invalid")
    if len(payload) != minimum + span_count * _SPAN.size:
        raise ValueError("repair-mask length is invalid")
    pixels = np.zeros((height, width), dtype=np.bool_)
    previous = (-1, -1, -1)
    for index in range(span_count):
        span = _SPAN.unpack_from(payload, minimum + index * _SPAN.size)
        y, x, length = span
        if length <= 0 or y >= height or x + length > width or span <= previous:
            raise ValueError("repair-mask span is invalid")
        if np.any(pixels[y, x : x + length]):
            raise ValueError("repair-mask spans overlap")
        pixels[y, x : x + length] = True
        previous = span
    if not np.any(pixels) or _encode_spans(pixels) != payload:
        raise ValueError("repair-mask encoding is noncanonical")
    pixels.flags.writeable = False
    return RepairMask(pixels, payload)


def build_union_repair_mask(
    failures: Iterable[RepairFailure], halo_um: float, mpp: float
) -> RepairMask:
    ordered = sorted(failures, key=lambda value: (value.y, value.x, value.height, value.width))
    if not ordered:
        raise ValueError("at least one failure is required")
    if halo_um < 0 or not math.isfinite(halo_um):
        raise ValueError("halo_um must be finite and non-negative")
    if mpp <= 0 or not math.isfinite(mpp):
        raise ValueError("mpp must be finite and positive")
    dimensions = {(item.image_height, item.image_width) for item in ordered}
    if len(dimensions) != 1:
        raise ValueError("all failures must refer to the same image")
    height, width = next(iter(dimensions))
    halo = math.ceil(halo_um / mpp)
    pixels = np.zeros((height, width), dtype=np.bool_)
    for item in ordered:
        x0 = max(0, item.x - halo)
        y0 = max(0, item.y - halo)
        x1 = min(width, item.x + item.width + halo)
        y1 = min(height, item.y + item.height + halo)
        pixels[y0:y1, x0:x1] = True
    pixels.flags.writeable = False
    return RepairMask(pixels=pixels, encoded=_encode_spans(pixels))
