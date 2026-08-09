from __future__ import annotations

import io
from email.message import Message

import numpy as np
import pytest
import tifffile

from denser.wsi.metadata import MetadataError
from denser.wsi.remote_metadata import (
    _read_prefix,
    parse_tiff_mpp,
    parse_tiff_mpp_from_reader,
)


def _tiff_bytes(**kwargs: object) -> bytes:
    stream = io.BytesIO()
    tifffile.imwrite(stream, np.zeros((16, 16, 3), dtype=np.uint8), metadata=None, **kwargs)
    return stream.getvalue()


def test_remote_metadata_prefers_aperio_mpp_without_decoding_pixels() -> None:
    payload = _tiff_bytes(description="Aperio Image Library|MPP = 0.2512|AppMag = 40")
    assert parse_tiff_mpp(payload) == (0.2512, "aperio_description")


def test_remote_metadata_uses_tiff_resolution_fallback() -> None:
    payload = _tiff_bytes(resolution=(40000, 40000), resolutionunit="CENTIMETER")
    mpp, source = parse_tiff_mpp(payload)
    assert mpp == pytest.approx(0.25)
    assert source == "tiff_resolution"


@pytest.mark.parametrize(
    ("kwargs", "expected", "source"),
    [
        ({"description": "Aperio Image Library|MPP = 0.247"}, 0.247, "aperio_description"),
        (
            {"resolution": (40000, 40000), "resolutionunit": "CENTIMETER"},
            0.25,
            "tiff_resolution",
        ),
    ],
)
def test_random_access_ifd_parser_follows_metadata_offsets(
    kwargs: dict[str, object], expected: float, source: str
) -> None:
    payload = _tiff_bytes(**kwargs)

    def read_range(start: int, length: int) -> bytes:
        value = payload[start : start + length]
        assert len(value) == length
        return value

    mpp, observed_source = parse_tiff_mpp_from_reader(read_range)
    assert mpp == pytest.approx(expected)
    assert observed_source == source


def test_remote_metadata_fails_closed_without_physical_scale() -> None:
    with pytest.raises(MetadataError):
        parse_tiff_mpp(_tiff_bytes())


def test_remote_probe_accepts_gdc_bare_content_range(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response(io.BytesIO):
        status = 206

        def __init__(self) -> None:
            super().__init__(b"abcd")
            self.headers = Message()
            self.headers["Content-Range"] = "0-3/100"

        def getcode(self) -> int:
            return self.status

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: _Response())
    assert _read_prefix("https://example.test/data", 4, timeout_seconds=1) == b"abcd"
