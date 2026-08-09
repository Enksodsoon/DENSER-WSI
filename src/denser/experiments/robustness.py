from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from denser.container.mcv1 import McV1CorruptionError, McV1Reader
from denser.container.mcv2 import McV2CorruptionError, McV2Reader
from denser.core.canonical import canonical_json_bytes


@dataclass(frozen=True, slots=True)
class RobustnessConfig:
    output_root: Path
    alternate_mpp_inputs: tuple[Path, ...] = ()
    external_inputs: tuple[Path, ...] = ()
    audit_only_inputs: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    status: str
    analysis_scope: str
    primary_tree_before: str
    primary_tree_after: str
    primary_files_examined: int
    missing_analyses: tuple[str, ...]
    cold_open_ms: float | None
    warm_open_ms: float | None
    corruption_fail_closed: bool | None


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in Path(root).rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run_robustness(config: RobustnessConfig, frozen_results: Path) -> RobustnessReport:
    primary = Path(frozen_results)
    before = sha256_tree(primary)
    containers = sorted((*primary.rglob("*.mcv1"), *primary.rglob("*.mcv2")))
    cold: float | None = None
    warm: float | None = None
    corruption: bool | None = None
    output = Path(config.output_root)
    output.mkdir(parents=True, exist_ok=True)
    if containers:
        reader_type = McV2Reader if containers[0].suffix == ".mcv2" else McV1Reader
        start = time.perf_counter_ns()
        reader = reader_type(containers[0])
        cold = (time.perf_counter_ns() - start) / 1_000_000
        start = time.perf_counter_ns()
        reader_type(containers[0])
        warm = (time.perf_counter_ns() - start) / 1_000_000
        probe = output / f"corruption-probe{containers[0].suffix}"
        shutil.copyfile(containers[0], probe)
        with probe.open("r+b") as stream:
            stream.seek(reader.packet_region_offset)
            byte = stream.read(1)
            stream.seek(reader.packet_region_offset)
            stream.write(bytes([byte[0] ^ 1]))
        try:
            damaged = reader_type(probe)
            first_address = damaged.addresses[0]
            damaged.read_tile(first_address)
        except (McV1CorruptionError, McV2CorruptionError):
            corruption = True
        else:
            corruption = False
        probe.unlink()
    missing: list[str] = []
    if not config.alternate_mpp_inputs:
        missing.append("alternate_mpp")
    if not config.external_inputs:
        missing.append("external_data")
    if not config.audit_only_inputs:
        missing.append("audit_only_evidence")
    if not containers:
        missing.extend(("cold_warm_latency", "corruption"))
    after = sha256_tree(primary)
    if after != before:
        raise RuntimeError("robustness analysis modified the immutable primary bundle")
    report = RobustnessReport(
        "complete" if not missing else "not_evaluable",
        "secondary_exploratory",
        before,
        after,
        len(containers),
        tuple(missing),
        cold,
        warm,
        corruption,
    )
    (output / "robustness-report.json").write_bytes(canonical_json_bytes(asdict(report)) + b"\n")
    return report
