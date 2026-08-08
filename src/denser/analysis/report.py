from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from denser.core.canonical import canonical_json_bytes


EXECUTION_STATUSES = {"complete", "resource_limited", "external_access_limited"}
SCIENTIFIC_OUTCOMES = {"positive", "negative", "inconclusive", "not_evaluable"}


@dataclass(frozen=True, slots=True)
class FinalReportInputs:
    execution_status: str
    scientific_outcome: str
    evaluable_slides: int
    expected_slides: int
    failed_slides_count: int
    missing_comparators: tuple[str, ...]
    threshold_misses: tuple[str, ...]
    limitations: tuple[str, ...]
    completed_tasks: int
    tests_passed: int
    tests_skipped: int
    reconstruction_checks_passed: int
    public_release_passed: bool

    def __post_init__(self) -> None:
        if self.execution_status not in EXECUTION_STATUSES:
            raise ValueError("unsupported execution status")
        if self.scientific_outcome not in SCIENTIFIC_OUTCOMES:
            raise ValueError("unsupported scientific outcome")
        if min(
            self.evaluable_slides,
            self.expected_slides,
            self.failed_slides_count,
            self.completed_tasks,
            self.tests_passed,
            self.tests_skipped,
            self.reconstruction_checks_passed,
        ) < 0:
            raise ValueError("report counts cannot be negative")


@dataclass(frozen=True, slots=True)
class CompletionMarker:
    version: str
    execution_status: str
    scientific_outcome: str
    completed_tasks: int
    evaluable_final_slides: int
    expected_final_slides: int
    source_data_processed: bool
    reconstruction_checks_passed: int
    tests_passed: int
    tests_skipped: int
    public_release_passed: bool
    artifact_digest: str


@dataclass(frozen=True, slots=True)
class FinalReportBundle:
    execution_status: str
    scientific_outcome: str
    evaluable_slides: int
    expected_slides: int
    failed_slides_count: int
    missing_comparators: tuple[str, ...]
    threshold_misses: tuple[str, ...]
    limitations: tuple[str, ...]
    vendor_source_endpoint_label: str
    completion_marker: CompletionMarker


def build_final_report(inputs: FinalReportInputs) -> FinalReportBundle:
    report_document = {
        "execution_status": inputs.execution_status,
        "scientific_outcome": inputs.scientific_outcome,
        "evaluable_slides": inputs.evaluable_slides,
        "expected_slides": inputs.expected_slides,
        "failed_slides_count": inputs.failed_slides_count,
        "missing_comparators": list(inputs.missing_comparators),
        "threshold_misses": list(inputs.threshold_misses),
        "limitations": list(inputs.limitations),
        "vendor_source_endpoint_label": "descriptive_not_primary",
    }
    artifact_digest = hashlib.sha256(canonical_json_bytes(report_document)).hexdigest()
    marker = CompletionMarker(
        "DENSER-autonomous-completion-1",
        inputs.execution_status,
        inputs.scientific_outcome,
        inputs.completed_tasks,
        inputs.evaluable_slides,
        inputs.expected_slides,
        inputs.evaluable_slides > 0,
        inputs.reconstruction_checks_passed,
        inputs.tests_passed,
        inputs.tests_skipped,
        inputs.public_release_passed,
        artifact_digest,
    )
    return FinalReportBundle(
        inputs.execution_status,
        inputs.scientific_outcome,
        inputs.evaluable_slides,
        inputs.expected_slides,
        inputs.failed_slides_count,
        inputs.missing_comparators,
        inputs.threshold_misses,
        inputs.limitations,
        "descriptive_not_primary",
        marker,
    )


def _report_document(bundle: FinalReportBundle) -> dict[str, object]:
    document = asdict(bundle)
    document.pop("completion_marker")
    return document


def write_final_report(output_root: Path, inputs: FinalReportInputs) -> FinalReportBundle:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    bundle = build_final_report(inputs)
    report_document = _report_document(bundle)
    (root / "final-report.json").write_bytes(canonical_json_bytes(report_document) + b"\n")
    (root / "AUTONOMOUS_RUN_COMPLETE.json").write_bytes(
        canonical_json_bytes(asdict(bundle.completion_marker)) + b"\n"
    )
    limitations = "# Limitations\n\n" + "\n".join(f"- {item}" for item in bundle.limitations) + "\n"
    (root / "limitations.md").write_text(limitations, encoding="utf-8", newline="\n")
    summary = (
        "# DENSER-WSI Final Report\n\n"
        f"Execution status: `{bundle.execution_status}`\n\n"
        f"Scientific outcome: `{bundle.scientific_outcome}`\n\n"
        f"Evaluable final slides: {bundle.evaluable_slides}/{bundle.expected_slides}\n\n"
        "The execution status and scientific outcome are separate. Missing, failed, larger, "
        "or unavailable results are retained. No clinical or universal-preservation claim is made.\n"
    )
    (root / "FINAL_REPORT.md").write_text(summary, encoding="utf-8", newline="\n")
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "DENSER-WSI-final-runtime",
        "documentNamespace": f"https://github.com/Enksodsoon/DENSER-WSI/sbom/{bundle.completion_marker.artifact_digest}",
        "packages": [
            {
                "name": name,
                "SPDXID": f"SPDXRef-Package-{name}",
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
            }
            for name, version in (
                ("python", "3.12.13"),
                ("openslide", "4.0.1"),
                ("libvips", "8.18.4"),
                ("libjpeg-turbo", "3.2.0"),
                ("openjpeg", "2.5.4"),
                ("libjxl", "0.12.0"),
                ("libavif", "1.4.1"),
                ("zstd", "1.5.7"),
            )
        ],
    }
    (root / "software-bill-of-materials.spdx.json").write_bytes(canonical_json_bytes(sbom) + b"\n")
    artifact_names = (
        "FINAL_REPORT.md",
        "final-report.json",
        "limitations.md",
        "software-bill-of-materials.spdx.json",
    )
    reproduction = {
        "version": "DENSER-reproducibility-manifest-1",
        "artifacts": [
            {"path": name, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
            for name in artifact_names
        ],
        "completed_tasks": inputs.completed_tasks,
    }
    (root / "reproducibility-manifest.json").write_bytes(
        canonical_json_bytes(reproduction) + b"\n"
    )
    return bundle
