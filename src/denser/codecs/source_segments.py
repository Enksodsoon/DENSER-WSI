from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import struct
from tempfile import NamedTemporaryFile
import zlib

import numpy as np

from denser.codecs.base import EncodedCandidate
from denser.core.models import ByteBreakdown
from denser.core.models import TileAddress


SOURCE_SEGMENT_CODEC_ID = "denser-source-segment-v2"
SOURCE_SEGMENT_PROFILE_ID = "source-segment-mosaic-v2"
DECODER_TIFF_JPEG = 1
DECODER_APERIO_JP2 = 2

_MAGIC = b"MCV2SS"
_VERSION = 1
_BODY = struct.Struct(">6sBBI8I32s")
_RECORD = struct.Struct(f">{_BODY.size}sI")


@dataclass(frozen=True, slots=True)
class SourceSegmentAllocationV2:
    """Canonical, source-identity-free instructions for decoding a segment mosaic."""

    decoder_code: int
    compression_code: int
    tile_width: int
    tile_height: int
    canvas_width: int
    canvas_height: int
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    payload_sha256: bytes

    def __post_init__(self) -> None:
        expected_compressions = {
            DECODER_TIFF_JPEG: {7},
            DECODER_APERIO_JP2: {33003, 33005},
        }
        if self.decoder_code not in expected_compressions:
            raise ValueError("unsupported source-segment decoder")
        if self.compression_code not in expected_compressions[self.decoder_code]:
            raise ValueError("compression is inconsistent with source-segment decoder")
        for name in (
            "tile_width",
            "tile_height",
            "canvas_width",
            "canvas_height",
            "crop_width",
            "crop_height",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.crop_x < 0 or self.crop_y < 0:
            raise ValueError("crop origin must be non-negative")
        if (
            self.crop_x + self.crop_width > self.canvas_width
            or self.crop_y + self.crop_height > self.canvas_height
        ):
            raise ValueError("crop must remain inside the decoded canvas")
        if not isinstance(self.payload_sha256, bytes) or len(self.payload_sha256) != 32:
            raise ValueError("payload_sha256 must contain 32 bytes")

    def encode(self) -> bytes:
        body = _BODY.pack(
            _MAGIC,
            _VERSION,
            self.decoder_code,
            self.compression_code,
            self.tile_width,
            self.tile_height,
            self.canvas_width,
            self.canvas_height,
            self.crop_x,
            self.crop_y,
            self.crop_width,
            self.crop_height,
            self.payload_sha256,
        )
        return _RECORD.pack(body, zlib.crc32(body))

    @classmethod
    def decode(cls, encoded: bytes) -> SourceSegmentAllocationV2:
        if len(encoded) != _RECORD.size:
            raise ValueError("source-segment allocation has a noncanonical length")
        body, checksum = _RECORD.unpack(encoded)
        if zlib.crc32(body) != checksum:
            raise ValueError("source-segment allocation checksum mismatch")
        values = _BODY.unpack(body)
        magic, version = values[:2]
        if magic != _MAGIC or version != _VERSION:
            raise ValueError("unknown source-segment allocation version")
        record = cls(*values[2:])
        if record.encode() != encoded:
            raise ValueError("source-segment allocation is noncanonical")
        return record


CanvasDecoder = Callable[[bytes, SourceSegmentAllocationV2], np.ndarray]


def build_source_segment_candidate(
    payload: bytes, metadata: SourceSegmentAllocationV2
) -> EncodedCandidate:
    if sha256(payload).digest() != metadata.payload_sha256:
        raise ValueError("source-segment payload digest mismatch")
    allocation_map = metadata.encode()
    return EncodedCandidate(
        codec_id=SOURCE_SEGMENT_CODEC_ID,
        profile_id=SOURCE_SEGMENT_PROFILE_ID,
        payload=payload,
        allocation_map=allocation_map,
        breakdown=ByteBreakdown(
            payload=len(payload), method_signaling=len(allocation_map)
        ),
        attestation=(("packet_kind", "self-contained-source-segment-mosaic"),),
    )


def _canonical_description(
    compression_code: int,
    width: int,
    height: int,
    tile_width: int,
    tile_height: int,
    source_description: str,
) -> str:
    quality_match = re.search(r"\bQ\s*=\s*(\d+)\b", source_description, re.IGNORECASE)
    quality = int(quality_match.group(1)) if quality_match else 0
    if compression_code == 7:
        return (
            "Aperio Image Library vMCV2 01\r\n"
            f"{width}x{height} ({tile_width}x{tile_height}) JPEG/RGB Q={quality}"
        )
    return (
        "Aperio Image Library vMCV2 01\r\n"
        f"{width}x{height} ({tile_width}x{tile_height}) J2K/YUV16 Q={quality}"
    )


def build_source_segment_candidate_from_svs(
    source_path: Path, address: TileAddress
) -> EncodedCandidate:
    """Copy only compressed source tiles needed for one level-0 random-access tile."""

    if address.level != 0:
        raise ValueError("source-segment extraction supports level 0 only")
    try:
        import tifffile
    except ImportError as error:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("tifffile and imagecodecs are required for segment extraction") from error

    source_path = Path(source_path)
    with tifffile.TiffFile(source_path) as source:
        page = source.pages[0]
        if not page.is_tiled or page.samplesperpixel != 3:
            raise ValueError("source slide must be a tiled three-channel TIFF")
        height, width = int(page.imagelength), int(page.imagewidth)
        if address.x + address.width > width or address.y + address.height > height:
            raise ValueError("requested tile lies outside level-0 bounds")
        compression_code = int(page.compression)
        if compression_code == 7:
            decoder_code = DECODER_TIFF_JPEG
        elif compression_code in {33003, 33005}:
            decoder_code = DECODER_APERIO_JP2
        else:
            raise ValueError("source slide uses an unsupported source-segment compression")

        tile_width = int(page.tilewidth)
        tile_height = int(page.tilelength)
        tiles_across = (width + tile_width - 1) // tile_width
        first_column = address.x // tile_width
        last_column = (address.x + address.width - 1) // tile_width
        first_row = address.y // tile_height
        last_row = (address.y + address.height - 1) // tile_height
        segment_indices = [
            row * tiles_across + column
            for row in range(first_row, last_row + 1)
            for column in range(first_column, last_column + 1)
        ]
        offsets = tuple(int(value) for value in page.dataoffsets)
        bytecounts = tuple(int(value) for value in page.databytecounts)
        if max(segment_indices) >= len(offsets) or len(offsets) != len(bytecounts):
            raise ValueError("source TIFF has an inconsistent compressed-segment table")
        with source_path.open("rb") as stream:
            segments: list[bytes] = []
            for index in segment_indices:
                stream.seek(offsets[index])
                segment = stream.read(bytecounts[index])
                if len(segment) != bytecounts[index]:
                    raise ValueError("source TIFF compressed segment is truncated")
                segments.append(segment)

        columns = last_column - first_column + 1
        rows = last_row - first_row + 1
        canvas_width = columns * tile_width
        canvas_height = rows * tile_height
        description = _canonical_description(
            compression_code,
            canvas_width,
            canvas_height,
            tile_width,
            tile_height,
            str(page.description or ""),
        )
        write_options: dict[str, object] = {
            "shape": (canvas_height, canvas_width, 3),
            "dtype": np.uint8,
            "tile": (tile_height, tile_width),
            "compression": page.compression,
            "photometric": page.photometric,
            "planarconfig": page.planarconfig,
            "metadata": None,
            "description": description,
            "software": False,
            "datetime": False,
        }
        if compression_code == 7 and page.jpegtables:
            write_options["jpegtables"] = page.jpegtables
            write_options["compressionargs"] = {"outcolorspace": "RGB"}
        if compression_code == 7 and "YCbCrSubSampling" in page.tags:
            sampling = tuple(int(value) for value in page.tags["YCbCrSubSampling"].value)
            if len(sampling) != 2:
                raise ValueError("source TIFF has an invalid JPEG subsampling tag")

    output = BytesIO()
    with tifffile.TiffWriter(output, byteorder="<") as writer:
        writer.write(iter(segments), **write_options)
    payload = output.getvalue()
    metadata = SourceSegmentAllocationV2(
        decoder_code=decoder_code,
        compression_code=compression_code,
        tile_width=tile_width,
        tile_height=tile_height,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        crop_x=address.x - first_column * tile_width,
        crop_y=address.y - first_row * tile_height,
        crop_width=address.width,
        crop_height=address.height,
        payload_sha256=sha256(payload).digest(),
    )
    return build_source_segment_candidate(payload, metadata)


def _decode_canvas(payload: bytes, record: SourceSegmentAllocationV2) -> np.ndarray:
    if record.decoder_code in {DECODER_TIFF_JPEG, DECODER_APERIO_JP2}:
        try:
            import openslide
        except ImportError as error:  # pragma: no cover - deployment dependency guard
            raise RuntimeError("OpenSlide is required for Aperio JP2 segments") from error
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=".svs", delete=False) as temporary:
                temporary.write(payload)
                temporary_path = Path(temporary.name)
            with openslide.OpenSlide(str(temporary_path)) as slide:
                image = slide.read_region(
                    (0, 0), 0, (record.canvas_width, record.canvas_height)
                ).convert("RGB")
                return np.asarray(image)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    raise ValueError("unsupported source-segment decoder")


def decode_source_segment_candidate(
    payload: bytes,
    allocation_map: bytes,
    shape: tuple[int, int, int],
    *,
    canvas_decoder: CanvasDecoder | None = None,
) -> np.ndarray:
    record = SourceSegmentAllocationV2.decode(allocation_map)
    if sha256(payload).digest() != record.payload_sha256:
        raise ValueError("source-segment payload digest mismatch")
    expected_shape = (record.crop_height, record.crop_width, 3)
    if shape != expected_shape:
        raise ValueError("requested shape is inconsistent with source-segment crop")
    decoder = canvas_decoder or _decode_canvas
    canvas = np.asarray(decoder(payload, record))
    canvas_shape = (record.canvas_height, record.canvas_width, 3)
    if canvas.dtype != np.uint8 or canvas.shape != canvas_shape:
        raise ValueError("source-segment decoder returned an invalid canvas")
    decoded = canvas[
        record.crop_y : record.crop_y + record.crop_height,
        record.crop_x : record.crop_x + record.crop_width,
    ]
    if decoded.shape != shape:
        raise ValueError("source-segment crop returned an invalid shape")
    return np.ascontiguousarray(decoded)
