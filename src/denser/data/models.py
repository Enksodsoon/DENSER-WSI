from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GdcSlideRecord:
    research_id: str
    file_uuid: str
    file_name: str
    project_id: str
    case_id: str
    primary_site: str | None
    stain_type: str
    magnification: float | None
    mpp: float | None
    file_size: int
    md5: str
    release: str | None
    access: str
    content_url: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadRecord:
    research_id: str
    destination: str
    byte_count: int
    source_md5: str
    sha256: str
    verified: bool
