from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class PublicReleasePolicy:
    forbidden_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                ".svs", ".vsi", ".ndpi", ".mrxs", ".scn", ".bif", ".czi",
                ".mcv1", ".parquet", ".tif", ".tiff",
            }
        )
    )
    forbidden_report_fields: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "case_id", "file_id", "research_id", "tile_x", "tile_y",
                "source_sha256", "signed_url", "absolute_path",
            }
        )
    )
    minimum_aggregate_cell_count: int = 5
    ignored_directories: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {".git", ".venv", ".pytest_cache", "__pycache__", ".mypy_cache"}
        )
    )


@dataclass(frozen=True, order=True)
class PublicReleaseFinding:
    code: str
    path: str
    detail: str = ""


@dataclass(frozen=True)
class PublicReleaseReport:
    findings: tuple[PublicReleaseFinding, ...]
    scanned_files: int

    @property
    def passed(self) -> bool:
        return not self.findings

    @property
    def error_codes(self) -> frozenset[str]:
        return frozenset(item.code for item in self.findings)


_LOCAL_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\", re.IGNORECASE),
    re.compile(r"/(?:home|Users)/[^/\s]+/"),
)
_SIGNED_URL_PATTERNS = (
    re.compile(r"[?&]X-Amz-Signature=", re.IGNORECASE),
    re.compile(r"[?&](?:sig|signature|token)=", re.IGNORECASE),
)


def _walk_json(value: object, path: str = "$") -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, child
            yield from _walk_json(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def check_public_release(root: Path, policy: PublicReleasePolicy) -> PublicReleaseReport:
    root = root.resolve()
    findings: list[PublicReleaseFinding] = []
    scanned_files = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file() or policy.ignored_directories.intersection(path.parts):
            continue
        scanned_files += 1
        relative = _relative(path, root)

        if path.is_symlink():
            findings.append(PublicReleaseFinding("symlink", relative))
            continue
        if path.suffix.lower() in policy.forbidden_extensions:
            findings.append(PublicReleaseFinding("forbidden_extension", relative))
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        if any(pattern.search(text) for pattern in _LOCAL_PATH_PATTERNS):
            findings.append(PublicReleaseFinding("absolute_local_path", relative))
        if any(pattern.search(text) for pattern in _SIGNED_URL_PATTERNS):
            findings.append(PublicReleaseFinding("signed_url", relative))

        if relative.startswith("reports/public/") and path.suffix.lower() == ".json":
            try:
                document = json.loads(text)
            except json.JSONDecodeError:
                findings.append(PublicReleaseFinding("invalid_public_json", relative))
                continue
            for json_path, value in _walk_json(document):
                field_name = json_path.rsplit(".", 1)[-1]
                if field_name in policy.forbidden_report_fields:
                    findings.append(
                        PublicReleaseFinding("forbidden_report_field", relative, json_path)
                    )
                if field_name == "count" and isinstance(value, int) and value < policy.minimum_aggregate_cell_count:
                    findings.append(
                        PublicReleaseFinding("small_aggregate_cell", relative, json_path)
                    )

    return PublicReleaseReport(tuple(sorted(set(findings))), scanned_files)
