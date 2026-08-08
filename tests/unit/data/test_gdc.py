from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from denser.data.download import DownloadIntegrityError, download_verified
from denser.data.gdc import GdcResponseError, build_gdc_query, query_open_he_slides
from denser.data.models import GdcSlideRecord


def test_query_requires_open_released_slide_images() -> None:
    query = build_gdc_query(("TCGA-LUAD",))
    assert query.filters_access == "open"
    assert query.filters_state == "released"
    assert query.filters_data_type == "Slide Image"
    assert query.filters_format == "SVS"
    assert query.size <= 500


class _RecordedClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.queries = []

    def fetch_files(self, query):  # type: ignore[no-untyped-def]
        self.queries.append(query)
        return self.response


def test_query_maps_valid_official_response() -> None:
    client = _RecordedClient(
        {
            "data": {
                "hits": [
                    {
                        "id": "file-1",
                        "file_name": "slide.svs",
                        "file_size": 123,
                        "md5sum": "0" * 32,
                        "access": "open",
                        "state": "released",
                        "data_type": "Slide Image",
                        "data_format": "SVS",
                        "cases": [
                            {
                                "case_id": "case-1",
                                "project": {"project_id": "TCGA-LUAD"},
                                "primary_site": "Bronchus and lung",
                            }
                        ],
                    }
                ],
                "pagination": {"total": 1},
            }
        }
    )
    records = query_open_he_slides(client, ("TCGA-LUAD",))
    assert len(records) == 1
    assert records[0].file_uuid == "file-1"
    assert records[0].project_id == "TCGA-LUAD"
    assert records[0].access == "open"
    assert records[0].research_id.startswith("RS-")


def test_query_rejects_malformed_response() -> None:
    with pytest.raises(GdcResponseError, match="hits"):
        query_open_he_slides(_RecordedClient({"data": {}}), ("TCGA-LUAD",))


def _serve_once(payload: bytes) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/data"


def _record(payload: bytes, url: str, *, md5: str | None = None) -> GdcSlideRecord:
    return GdcSlideRecord(
        research_id="RS-test",
        file_uuid="file-1",
        file_name="slide.svs",
        project_id="TCGA-LUAD",
        case_id="case-1",
        primary_site="Bronchus and lung",
        stain_type="H&E",
        magnification=None,
        mpp=None,
        file_size=len(payload),
        md5=md5 or hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        release=None,
        access="open",
        content_url=url,
    )


def test_download_verified_streams_hashes_and_atomically_renames(tmp_path: Path) -> None:
    payload = b"synthetic-slide-bytes"
    server, url = _serve_once(payload)
    try:
        destination = tmp_path / "sources" / "slide.svs"
        result = download_verified(_record(payload, url), destination)
    finally:
        server.shutdown()
        server.server_close()
    assert destination.read_bytes() == payload
    assert result.verified
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert not list(destination.parent.glob("*.part"))


def test_download_mismatch_is_quarantined(tmp_path: Path) -> None:
    payload = b"corrupt"
    server, url = _serve_once(payload)
    destination = tmp_path / "sources" / "slide.svs"
    try:
        with pytest.raises(DownloadIntegrityError, match="MD5"):
            download_verified(_record(payload, url, md5="0" * 32), destination)
    finally:
        server.shutdown()
        server.server_close()
    assert not destination.exists()
    assert list((tmp_path / "quarantine").glob("*.part"))
