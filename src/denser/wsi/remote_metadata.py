from __future__ import annotations

import io
import math
import re
import struct
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

import tifffile

from denser.wsi.metadata import MetadataError


_APERIO_MPP = re.compile(r"(?:^|[|\r\n])\s*MPP\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_MAX_IFD_ENTRIES = 4096
_MAX_TAG_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class RemotePhysicalMetadata:
    mpp: float
    bytes_requested: int
    source: str


def _rational(value: object) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]) / float(value[1])
    return float(value)  # type: ignore[arg-type]


def parse_tiff_mpp(payload: bytes) -> tuple[float, str]:
    """Read physical scale from a TIFF prefix without decoding image pixels."""

    try:
        with tifffile.TiffFile(io.BytesIO(payload)) as tiff:
            page = tiff.pages[0]
            description = page.description or ""
            match = _APERIO_MPP.search(description)
            if match is not None:
                mpp = float(match.group(1))
                source = "aperio_description"
            else:
                x_tag = page.tags.get("XResolution")
                y_tag = page.tags.get("YResolution")
                unit_tag = page.tags.get("ResolutionUnit")
                if x_tag is None or y_tag is None or unit_tag is None:
                    raise MetadataError("TIFF physical-scale metadata is missing")
                x_resolution = _rational(x_tag.value)
                y_resolution = _rational(y_tag.value)
                unit = int(unit_tag.value)
                micrometres_per_unit = {2: 25400.0, 3: 10000.0}.get(unit)
                if micrometres_per_unit is None:
                    raise MetadataError("TIFF physical-scale unit is unsupported")
                mpp_x = micrometres_per_unit / x_resolution
                mpp_y = micrometres_per_unit / y_resolution
                average = (mpp_x + mpp_y) / 2
                if abs(mpp_x - mpp_y) / average > 0.10:
                    raise MetadataError("TIFF physical-scale axes are inconsistent")
                mpp = average
                source = "tiff_resolution"
    except MetadataError:
        raise
    except (OSError, ValueError, IndexError, ZeroDivisionError) as error:
        raise MetadataError("TIFF metadata prefix is incomplete or invalid") from error
    if not math.isfinite(mpp) or not 0.05 <= mpp <= 5.0:
        raise MetadataError("TIFF physical scale is outside supported bounds")
    return mpp, source


def _read_range(
    url: str, start: int, byte_count: int, *, timeout_seconds: float
) -> bytes:
    if start < 0 or byte_count <= 0:
        raise ValueError("remote metadata byte range is invalid")
    end = start + byte_count - 1
    request = urllib.request.Request(
        url,
        headers={
            "Range": f"bytes={start}-{end}",
            "User-Agent": "DENSER-WSI/0.3 physical-metadata-preflight",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status = getattr(response, "status", response.getcode())
        payload = response.read(byte_count + 1)
        if status not in {200, 206}:
            raise OSError("remote metadata probe returned an unsupported status")
        if status == 200 and (start != 0 or len(payload) > byte_count):
            raise OSError("remote endpoint ignored the bounded Range request")
        if status == 206:
            content_range = response.headers.get("Content-Range", "")
            match = re.fullmatch(r"(?:bytes )?(\d+)-(\d+)/(?:\d+|\*)", content_range)
            if (
                match is None
                or int(match.group(1)) != start
                or int(match.group(2)) - start + 1 != len(payload)
            ):
                raise OSError("remote metadata probe returned a mismatched range")
        return payload[:byte_count]


def _read_prefix(url: str, byte_count: int, *, timeout_seconds: float) -> bytes:
    return _read_range(url, 0, byte_count, timeout_seconds=timeout_seconds)


def _unpack_integer(data: bytes, endian: str) -> int:
    return int.from_bytes(data, "little" if endian == "<" else "big")


def _ifd_tag_values(
    read_range: Callable[[int, int], bytes],
) -> tuple[str, dict[int, bytes]]:
    header = read_range(0, 16)
    if header[:2] == b"II":
        endian = "<"
    elif header[:2] == b"MM":
        endian = ">"
    else:
        raise MetadataError("remote source is not a TIFF stream")
    magic = struct.unpack(f"{endian}H", header[2:4])[0]
    if magic == 42:
        count_size, entry_size, slot_size = 2, 12, 4
        first_ifd = _unpack_integer(header[4:8], endian)
        count_format = "H"
    elif magic == 43 and struct.unpack(f"{endian}H", header[4:6])[0] == 8:
        count_size, entry_size, slot_size = 8, 20, 8
        first_ifd = _unpack_integer(header[8:16], endian)
        count_format = "Q"
    else:
        raise MetadataError("remote TIFF version is unsupported")
    count_bytes = read_range(first_ifd, count_size)
    entry_count = struct.unpack(f"{endian}{count_format}", count_bytes)[0]
    if entry_count <= 0 or entry_count > _MAX_IFD_ENTRIES:
        raise MetadataError("remote TIFF directory entry count is invalid")
    entries = read_range(first_ifd + count_size, entry_count * entry_size)
    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 12: 8, 16: 8, 17: 8, 18: 8}
    wanted = {270, 282, 283, 296}
    values: dict[int, bytes] = {}
    for ordinal in range(entry_count):
        entry = entries[ordinal * entry_size : (ordinal + 1) * entry_size]
        tag, data_type = struct.unpack(f"{endian}HH", entry[:4])
        if tag not in wanted or data_type not in type_sizes:
            continue
        if slot_size == 4:
            count = _unpack_integer(entry[4:8], endian)
            slot = entry[8:12]
        else:
            count = _unpack_integer(entry[4:12], endian)
            slot = entry[12:20]
        value_size = count * type_sizes[data_type]
        if value_size <= 0 or value_size > _MAX_TAG_BYTES:
            raise MetadataError("remote TIFF metadata tag size is invalid")
        if value_size <= slot_size:
            value = slot[:value_size]
        else:
            value = read_range(_unpack_integer(slot, endian), value_size)
        values[tag] = bytes((data_type,)) + value
    return endian, values


def parse_tiff_mpp_from_reader(
    read_range: Callable[[int, int], bytes],
) -> tuple[float, str]:
    """Resolve TIFF physical scale through bounded random-access metadata reads."""

    endian, tags = _ifd_tag_values(read_range)
    description = tags.get(270, b"")
    if description and description[0] == 2:
        text = description[1:].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        match = _APERIO_MPP.search(text)
        if match is not None:
            mpp = float(match.group(1))
            if math.isfinite(mpp) and 0.05 <= mpp <= 5.0:
                return mpp, "aperio_description"
            raise MetadataError("TIFF physical scale is outside supported bounds")
    try:
        x_type, x_raw = tags[282][0], tags[282][1:]
        y_type, y_raw = tags[283][0], tags[283][1:]
        unit_type, unit_raw = tags[296][0], tags[296][1:]
    except KeyError as error:
        raise MetadataError("TIFF physical-scale metadata is missing") from error
    if x_type != 5 or y_type != 5 or unit_type != 3:
        raise MetadataError("TIFF physical-scale tag types are invalid")

    def rational(raw: bytes) -> float:
        numerator, denominator = struct.unpack(f"{endian}II", raw[:8])
        return numerator / denominator

    x_resolution = rational(x_raw)
    y_resolution = rational(y_raw)
    unit = struct.unpack(f"{endian}H", unit_raw[:2])[0]
    micrometres_per_unit = {2: 25400.0, 3: 10000.0}.get(unit)
    if micrometres_per_unit is None:
        raise MetadataError("TIFF physical-scale unit is unsupported")
    mpp_x = micrometres_per_unit / x_resolution
    mpp_y = micrometres_per_unit / y_resolution
    mpp = (mpp_x + mpp_y) / 2
    if (
        not math.isfinite(mpp)
        or not 0.05 <= mpp <= 5.0
        or abs(mpp_x - mpp_y) / mpp > 0.10
    ):
        raise MetadataError("TIFF physical-scale axes are invalid")
    return mpp, "tiff_resolution"


def probe_remote_tiff_mpp(
    url: str,
    *,
    timeout_seconds: float = 60.0,
) -> RemotePhysicalMetadata:
    if not url.lower().startswith("https://"):
        raise ValueError("remote source metadata requires HTTPS")
    bytes_requested = 0

    def read_range(start: int, byte_count: int) -> bytes:
        nonlocal bytes_requested
        if bytes_requested + byte_count > _MAX_TAG_BYTES:
            raise MetadataError("remote TIFF metadata probe exceeded its byte budget")
        value = _read_range(
            url, start, byte_count, timeout_seconds=timeout_seconds
        )
        bytes_requested += len(value)
        return value

    mpp, source = parse_tiff_mpp_from_reader(read_range)
    return RemotePhysicalMetadata(mpp, bytes_requested, source)
