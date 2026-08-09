from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


_VERSION = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    version_args: tuple[str, ...]
    build_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolRecord:
    name: str
    available: bool
    path: str | None
    version: tuple[int, int, int] | None
    executable_sha256: str | None
    error_code: str | None
    build_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolchainReport:
    tools: tuple[ToolRecord, ...]
    container_digest: str | None = None


DEFAULT_TOOL_SPECS = (
    ToolSpec("python", ("--version",), ("official-python-3.12-slim",)),
    ToolSpec("vips", ("--version",), ("buildtype=release", "introspection=disabled")),
    ToolSpec("openslide-show-properties", ("--version",), ("buildtype=release",)),
    ToolSpec("cjpeg", ("-version",), ("CMAKE_BUILD_TYPE=Release", "WITH_TOOLS=ON")),
    ToolSpec("opj_compress", ("-h",), ("CMAKE_BUILD_TYPE=Release", "BUILD_CODEC=ON")),
    ToolSpec("cjxl", ("--version",), ("CMAKE_BUILD_TYPE=Release", "JPEGXL_ENABLE_TOOLS=ON")),
    ToolSpec("avifenc", ("--version",), ("AVIF_CODEC_AOM=SYSTEM", "AVIF_LIBYUV=OFF")),
    ToolSpec("zstd", ("--version",), ("CMAKE_BUILD_TYPE=Release",)),
)


def parse_version(text: str) -> tuple[int, int, int]:
    match = _VERSION.search(text)
    if match is None:
        raise ValueError("tool output contains no semantic version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_tool(spec: ToolSpec) -> ToolRecord:
    executable = shutil.which(spec.name)
    if executable is None:
        return ToolRecord(
            spec.name, False, None, None, None, "executable_not_found", spec.build_flags
        )
    path = Path(executable).resolve()
    try:
        completed = subprocess.run(
            [str(path), *spec.version_args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ToolRecord(
            spec.name,
            False,
            str(path),
            None,
            None,
            "version_probe_failed",
            spec.build_flags,
        )
    output = f"{completed.stdout}\n{completed.stderr}"
    try:
        version = parse_version(output)
    except ValueError:
        return ToolRecord(
            spec.name,
            False,
            str(path),
            None,
            None,
            "version_unparseable",
            spec.build_flags,
        )
    return ToolRecord(
        spec.name, True, str(path), version, _sha256_file(path), None, spec.build_flags
    )


def probe_toolchain(
    specs: tuple[ToolSpec, ...] = DEFAULT_TOOL_SPECS,
    *,
    container_digest: str | None = None,
) -> ToolchainReport:
    return ToolchainReport(
        tuple(probe_tool(spec) for spec in specs), container_digest=container_digest
    )
