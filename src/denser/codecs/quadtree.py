from __future__ import annotations

import hashlib
import struct
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.codecs.jpeg import JpegCodec
from denser.codecs.jpegxl import JpegXlCodec
from denser.core.models import ByteBreakdown


MAGIC = b"QAM2"
HEADER = struct.Struct(">4sHHHHI32s")
LEAF = struct.Struct(">HHHHBI")
QUALITY_DISTANCES = (0.5, 1.0, 2.0)
JPEG_QUALITIES = (90, 80, 70)


class LeafCodec(Protocol):
    def encode(self, rgb: np.ndarray) -> EncodedCandidate: ...

    def decode(self, payload: bytes, shape: tuple[int, int, int]) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class QuadtreeLeaf:
    x: int
    y: int
    width: int
    height: int
    quality_code: int
    payload_length: int


@dataclass(frozen=True, slots=True)
class QuadtreeAllocationMap:
    width: int
    height: int
    min_leaf: int
    leaves: tuple[QuadtreeLeaf, ...]

    def __post_init__(self) -> None:
        if min(self.width, self.height, self.min_leaf) <= 0 or not self.leaves:
            raise ValueError("quadtree allocation dimensions are invalid")
        coverage = np.zeros((self.height, self.width), dtype=np.uint8)
        previous = (-1, -1)
        for leaf in self.leaves:
            if (
                min(leaf.width, leaf.height, leaf.payload_length) <= 0
                or leaf.quality_code not in range(len(QUALITY_DISTANCES))
                or leaf.x + leaf.width > self.width
                or leaf.y + leaf.height > self.height
                or (leaf.y, leaf.x) <= previous
            ):
                raise ValueError("quadtree leaf is invalid or noncanonical")
            coverage[leaf.y : leaf.y + leaf.height, leaf.x : leaf.x + leaf.width] += 1
            previous = (leaf.y, leaf.x)
        if not np.all(coverage == 1):
            raise ValueError("quadtree leaves must cover every pixel exactly once")

    def encode(self) -> bytes:
        body = b"".join(
            LEAF.pack(
                leaf.x,
                leaf.y,
                leaf.width,
                leaf.height,
                leaf.quality_code,
                leaf.payload_length,
            )
            for leaf in self.leaves
        )
        return HEADER.pack(
            MAGIC,
            self.width,
            self.height,
            self.min_leaf,
            len(self.leaves),
            sum(leaf.payload_length for leaf in self.leaves),
            hashlib.sha256(body).digest(),
        ) + body

    @classmethod
    def decode(cls, payload: bytes) -> QuadtreeAllocationMap:
        if len(payload) < HEADER.size:
            raise ValueError("quadtree allocation map is truncated")
        magic, width, height, min_leaf, count, total_payload, digest = HEADER.unpack_from(payload)
        body = payload[HEADER.size:]
        if magic != MAGIC or len(body) != count * LEAF.size or hashlib.sha256(body).digest() != digest:
            raise ValueError("quadtree allocation-map integrity failed")
        leaves = tuple(QuadtreeLeaf(*LEAF.unpack_from(body, offset)) for offset in range(0, len(body), LEAF.size))
        result = cls(width, height, min_leaf, leaves)
        if sum(item.payload_length for item in leaves) != total_payload or result.encode() != payload:
            raise ValueError("quadtree allocation map is noncanonical")
        return result


def _regions(sensitivity: np.ndarray, min_leaf: int) -> list[tuple[int, int, int, int, float]]:
    height, width, _ = sensitivity.shape
    regions: list[tuple[int, int, int, int, float]] = []

    def visit(x: int, y: int, region_width: int, region_height: int) -> None:
        values = sensitivity[y : y + region_height, x : x + region_width]
        mean = float(np.mean(values))
        relative_std = float(np.std(values) / max(mean, 1e-12))
        if min(region_width, region_height) >= min_leaf * 2 and relative_std > 0.35:
            left = region_width // 2
            top = region_height // 2
            for child_x, child_y, child_width, child_height in (
                (x, y, left, top),
                (x + left, y, region_width - left, top),
                (x, y + top, left, region_height - top),
                (x + left, y + top, region_width - left, region_height - top),
            ):
                visit(child_x, child_y, child_width, child_height)
        else:
            regions.append((x, y, region_width, region_height, mean))

    visit(0, 0, width, height)
    return sorted(regions, key=lambda item: (item[1], item[0]))


def build_jpegxl_quadtree_candidate(
    rgb: np.ndarray,
    sensitivity: np.ndarray,
    *,
    min_leaf: int = 128,
    allocation_quantiles: tuple[float, float] = (0.5, 0.75),
    allocation_policy_id: str = "alloc25-25-50",
    fixed_quality_code: int | None = None,
    codec_factory: Callable[[float], LeafCodec] = JpegXlCodec,
) -> EncodedCandidate:
    pixels = np.asarray(rgb)
    values = np.asarray(sensitivity, dtype=np.float64)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3 or values.shape != pixels.shape:
        raise ValueError("quadtree candidate requires matching uint8 RGB and sensitivity")
    if min_leaf < 8 or min_leaf & (min_leaf - 1):
        raise ValueError("quadtree minimum leaf must be a power of two of at least eight")
    lower_quantile, upper_quantile = allocation_quantiles
    if (
        not 0 <= lower_quantile < upper_quantile <= 1
        or not allocation_policy_id
        or (fixed_quality_code is not None and fixed_quality_code not in range(len(QUALITY_DISTANCES)))
    ):
        raise ValueError("quadtree allocation policy is invalid")
    regions = _regions(values, min_leaf)
    means = np.asarray([item[4] for item in regions])
    lower, upper = (
        np.quantile(means, allocation_quantiles)
        if len(means) > 1
        else (means[0], means[0])
    )
    codes = (
        [fixed_quality_code] * len(regions)
        if fixed_quality_code is not None
        else [0 if mean >= upper else 1 if mean >= lower else 2 for *_region, mean in regions]
    )

    def encode_leaf(item):  # type: ignore[no-untyped-def]
        (x, y, width, height, _mean), code = item
        return codec_factory(QUALITY_DISTANCES[code]).encode(pixels[y : y + height, x : x + width])

    with ThreadPoolExecutor(max_workers=min(2, len(regions))) as pool:
        encoded = list(pool.map(encode_leaf, zip(regions, codes, strict=True)))
    leaves = tuple(
        QuadtreeLeaf(x, y, width, height, code, len(candidate.payload))
        for (x, y, width, height, _mean), code, candidate in zip(regions, codes, encoded, strict=True)
    )
    allocation = QuadtreeAllocationMap(pixels.shape[1], pixels.shape[0], min_leaf, leaves).encode()
    payload = b"".join(item.payload for item in encoded)
    profile = (
        f"jxl-evidence-quadtree-min{min_leaf}-d0.5-1-2-{allocation_policy_id}"
    )
    return EncodedCandidate(
        "denser-quadtree-jxl-v2",
        profile,
        payload,
        ByteBreakdown(payload=len(payload), method_signaling=len(allocation)),
        allocation_map=allocation,
    )


def build_jpegxl_quadtree_candidates(
    rgb: np.ndarray,
    sensitivity: np.ndarray,
    *,
    min_leaf: int = 128,
    codec_factory: Callable[[float], LeafCodec] = JpegXlCodec,
) -> list[EncodedCandidate]:
    policies = (
        ((0.5, 0.75), "alloc25-25-50", None),
        ((0.25, 0.5), "alloc50-25-25", None),
        ((0.0, 0.25), "alloc75-25-0", None),
        ((0.0, 0.25), "all-d0.5", 0),
    )
    return [
        build_jpegxl_quadtree_candidate(
            rgb,
            sensitivity,
            min_leaf=min_leaf,
            allocation_quantiles=quantiles,
            allocation_policy_id=policy_id,
            fixed_quality_code=fixed_quality_code,
            codec_factory=codec_factory,
        )
        for quantiles, policy_id, fixed_quality_code in policies
    ]


def build_jpeg_quadtree_candidate(
    rgb: np.ndarray,
    sensitivity: np.ndarray,
    *,
    min_leaf: int = 128,
    allocation_quantiles: tuple[float, float] = (0.5, 0.75),
    allocation_policy_id: str = "alloc25-25-50",
    fixed_quality_code: int | None = None,
    codec_factory: Callable[[int], LeafCodec] = JpegCodec,
) -> EncodedCandidate:
    pixels = np.asarray(rgb)
    values = np.asarray(sensitivity, dtype=np.float64)
    if (
        pixels.dtype != np.uint8
        or pixels.ndim != 3
        or pixels.shape[2] != 3
        or values.shape != pixels.shape
    ):
        raise ValueError("JPEG quadtree requires matching uint8 RGB and sensitivity")
    if min_leaf < 8 or min_leaf & (min_leaf - 1):
        raise ValueError("quadtree minimum leaf must be a power of two of at least eight")
    lower_quantile, upper_quantile = allocation_quantiles
    if (
        not 0 <= lower_quantile < upper_quantile <= 1
        or not allocation_policy_id
        or (
            fixed_quality_code is not None
            and fixed_quality_code not in range(len(JPEG_QUALITIES))
        )
    ):
        raise ValueError("JPEG quadtree allocation policy is invalid")
    regions = _regions(values, min_leaf)
    means = np.asarray([item[4] for item in regions])
    lower, upper = (
        np.quantile(means, allocation_quantiles)
        if len(means) > 1
        else (means[0], means[0])
    )
    codes = (
        [fixed_quality_code] * len(regions)
        if fixed_quality_code is not None
        else [
            0 if mean >= upper else 1 if mean >= lower else 2
            for *_region, mean in regions
        ]
    )

    def encode_leaf(item):  # type: ignore[no-untyped-def]
        (x, y, width, height, _mean), code = item
        return codec_factory(JPEG_QUALITIES[code]).encode(
            pixels[y : y + height, x : x + width]
        )

    with ThreadPoolExecutor(max_workers=min(2, len(regions))) as pool:
        encoded = list(pool.map(encode_leaf, zip(regions, codes, strict=True)))
    leaves = tuple(
        QuadtreeLeaf(x, y, width, height, code, len(candidate.payload))
        for (x, y, width, height, _mean), code, candidate in zip(
            regions, codes, encoded, strict=True
        )
    )
    allocation = QuadtreeAllocationMap(
        pixels.shape[1], pixels.shape[0], min_leaf, leaves
    ).encode()
    payload = b"".join(item.payload for item in encoded)
    return EncodedCandidate(
        "denser-quadtree-jpeg-v2",
        f"jpeg-evidence-quadtree-min{min_leaf}-q90-80-70-{allocation_policy_id}",
        payload,
        ByteBreakdown(payload=len(payload), method_signaling=len(allocation)),
        allocation_map=allocation,
    )


def build_jpeg_quadtree_candidates(
    rgb: np.ndarray,
    sensitivity: np.ndarray,
    *,
    min_leaf: int = 128,
    codec_factory: Callable[[int], LeafCodec] = JpegCodec,
) -> list[EncodedCandidate]:
    policies = (
        ((0.5, 0.75), "alloc25-25-50", None),
        ((0.25, 0.5), "alloc50-25-25", None),
        ((0.0, 0.25), "alloc75-25-0", None),
        ((0.0, 0.25), "all-q90", 0),
    )
    return [
        build_jpeg_quadtree_candidate(
            rgb,
            sensitivity,
            min_leaf=min_leaf,
            allocation_quantiles=quantiles,
            allocation_policy_id=policy_id,
            fixed_quality_code=fixed_quality_code,
            codec_factory=codec_factory,
        )
        for quantiles, policy_id, fixed_quality_code in policies
    ]


def decode_jpegxl_quadtree_candidate(
    payload: bytes,
    allocation_map: bytes,
    *,
    codec_factory: Callable[[float], LeafCodec] = JpegXlCodec,
) -> np.ndarray:
    allocation = QuadtreeAllocationMap.decode(allocation_map)
    if len(payload) != sum(item.payload_length for item in allocation.leaves):
        raise ValueError("quadtree payload length does not match allocation map")
    decoded = np.empty((allocation.height, allocation.width, 3), dtype=np.uint8)
    offset = 0
    for leaf in allocation.leaves:
        child = payload[offset : offset + leaf.payload_length]
        shape = (leaf.height, leaf.width, 3)
        decoded[leaf.y : leaf.y + leaf.height, leaf.x : leaf.x + leaf.width] = codec_factory(
            QUALITY_DISTANCES[leaf.quality_code]
        ).decode(child, shape)
        offset += leaf.payload_length
    return decoded


def decode_jpeg_quadtree_candidate(
    payload: bytes,
    allocation_map: bytes,
    *,
    codec_factory: Callable[[int], LeafCodec] = JpegCodec,
) -> np.ndarray:
    allocation = QuadtreeAllocationMap.decode(allocation_map)
    if len(payload) != sum(item.payload_length for item in allocation.leaves):
        raise ValueError("JPEG quadtree payload length does not match allocation map")
    decoded = np.empty((allocation.height, allocation.width, 3), dtype=np.uint8)
    offset = 0
    for leaf in allocation.leaves:
        child = payload[offset : offset + leaf.payload_length]
        shape = (leaf.height, leaf.width, 3)
        decoded[
            leaf.y : leaf.y + leaf.height, leaf.x : leaf.x + leaf.width
        ] = codec_factory(JPEG_QUALITIES[leaf.quality_code]).decode(child, shape)
        offset += leaf.payload_length
    return decoded
