from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Protocol

from denser.data.models import GdcSlideRecord


FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"


class GdcResponseError(RuntimeError):
    """The official API returned a response outside the declared contract."""


@dataclass(frozen=True, slots=True)
class GdcQuery:
    projects: tuple[str, ...]
    filters_access: str = "open"
    filters_state: str = "released"
    filters_data_type: str = "Slide Image"
    filters_format: str = "SVS"
    size: int = 500

    def as_api_params(self, *, offset: int = 0) -> dict[str, str]:
        clauses = (
            ("cases.project.project_id", list(self.projects)),
            ("access", [self.filters_access]),
            ("state", [self.filters_state]),
            ("data_type", [self.filters_data_type]),
            ("data_format", [self.filters_format]),
        )
        filters = {
            "op": "and",
            "content": [
                {"op": "in", "content": {"field": field, "value": value}}
                for field, value in clauses
            ],
        }
        fields = (
            "id,file_name,file_size,md5sum,access,state,data_type,data_format,"
            "created_datetime,updated_datetime,cases.case_id,cases.primary_site,"
            "cases.project.project_id"
        )
        return {
            "filters": json.dumps(filters, sort_keys=True, separators=(",", ":")),
            "fields": fields,
            "format": "JSON",
            "from": str(offset),
            "size": str(self.size),
        }


def build_gdc_query(projects: tuple[str, ...]) -> GdcQuery:
    if not projects or any(not project.startswith("TCGA-") for project in projects):
        raise ValueError("at least one valid TCGA project is required")
    return GdcQuery(tuple(dict.fromkeys(projects)))


class GdcClientLike(Protocol):
    def fetch_files(self, query: GdcQuery) -> dict[str, object]: ...


class GdcClient:
    def __init__(
        self,
        *,
        endpoint: str = FILES_ENDPOINT,
        retries: int = 3,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not 0 <= retries <= 5:
            raise ValueError("retries must be between zero and five")
        self.endpoint = endpoint
        self.retries = retries
        self.timeout_seconds = timeout_seconds

    def _request_page(self, query: GdcQuery, offset: int) -> dict[str, object]:
        body = urllib.parse.urlencode(query.as_api_params(offset=offset)).encode("ascii")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read())
                if not isinstance(payload, dict):
                    raise GdcResponseError("GDC response root must be an object")
                return payload
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == self.retries:
                    raise GdcResponseError("bounded GDC request failed") from error
                time.sleep(0.25 * (2**attempt))
        raise AssertionError("unreachable retry state")

    def fetch_files(self, query: GdcQuery) -> dict[str, object]:
        hits: list[object] = []
        offset = 0
        total: int | None = None
        while total is None or offset < total:
            page = self._request_page(query, offset)
            data = page.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
                raise GdcResponseError("GDC response is missing data.hits")
            page_hits = data["hits"]
            pagination = data.get("pagination")
            if not isinstance(pagination, dict) or not isinstance(pagination.get("total"), int):
                raise GdcResponseError("GDC response is missing pagination.total")
            total = pagination["total"]
            hits.extend(page_hits)
            offset += len(page_hits)
            if not page_hits:
                break
        return {"data": {"hits": hits, "pagination": {"total": total or 0}}}


def _required_text(hit: dict[str, object], key: str) -> str:
    value = hit.get(key)
    if not isinstance(value, str) or not value:
        raise GdcResponseError(f"GDC hit is missing {key}")
    return value


def query_open_he_slides(
    client: GdcClientLike, projects: tuple[str, ...]
) -> list[GdcSlideRecord]:
    query = build_gdc_query(projects)
    response = client.fetch_files(query)
    data = response.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
        raise GdcResponseError("GDC response is missing data.hits")
    records: list[GdcSlideRecord] = []
    for raw_hit in data["hits"]:
        if not isinstance(raw_hit, dict):
            raise GdcResponseError("GDC hit must be an object")
        if raw_hit.get("access") != "open" or raw_hit.get("state") != "released":
            raise GdcResponseError("GDC hit violates open/released query contract")
        if raw_hit.get("data_type") != "Slide Image" or raw_hit.get("data_format") != "SVS":
            raise GdcResponseError("GDC hit violates slide/SVS query contract")
        cases = raw_hit.get("cases")
        if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], dict):
            raise GdcResponseError("GDC hit must resolve to exactly one case")
        case = cases[0]
        project = case.get("project")
        if not isinstance(project, dict):
            raise GdcResponseError("GDC hit is missing case project")
        file_size = raw_hit.get("file_size")
        if not isinstance(file_size, int) or file_size <= 0:
            raise GdcResponseError("GDC hit has invalid file_size")
        records.append(
            GdcSlideRecord(
                research_id=f"RS-{uuid.uuid4().hex}",
                file_uuid=_required_text(raw_hit, "id"),
                file_name=_required_text(raw_hit, "file_name"),
                project_id=_required_text(project, "project_id"),
                case_id=_required_text(case, "case_id"),
                primary_site=case.get("primary_site")
                if isinstance(case.get("primary_site"), str)
                else None,
                stain_type="H&E",
                magnification=None,
                mpp=None,
                file_size=file_size,
                md5=_required_text(raw_hit, "md5sum").lower(),
                release=raw_hit.get("updated_datetime")
                if isinstance(raw_hit.get("updated_datetime"), str)
                else None,
                access="open",
            )
        )
    return records
