from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from denser.analysis.report import FinalReportInputs, build_final_report, write_final_report


def fixture_inputs_with_failures() -> FinalReportInputs:
    return FinalReportInputs(
        execution_status="external_access_limited",
        scientific_outcome="not_evaluable",
        evaluable_slides=0,
        expected_slides=18,
        failed_slides_count=2,
        missing_comparators=("avif",),
        threshold_misses=("minimum_final_slides",),
        limitations=("Real source slides were not available to the execution runtime.",),
        completed_tasks=29,
        tests_passed=180,
        tests_skipped=4,
        reconstruction_checks_passed=17,
        public_release_passed=True,
    )


def test_final_report_includes_negative_and_missing_results() -> None:
    report = build_final_report(fixture_inputs_with_failures())
    assert report.failed_slides_count == 2
    assert report.missing_comparators == ("avif",)
    assert report.vendor_source_endpoint_label == "descriptive_not_primary"


def test_completion_separates_execution_from_scientific_outcome(tmp_path: Path) -> None:
    bundle = write_final_report(tmp_path, fixture_inputs_with_failures())
    marker = bundle.completion_marker
    assert marker.execution_status in {"complete", "resource_limited", "external_access_limited"}
    assert marker.scientific_outcome in {"positive", "negative", "inconclusive", "not_evaluable"}
    schema = json.loads(Path("schemas/completion_marker.schema.json").read_text(encoding="utf-8"))
    document = json.loads((tmp_path / "AUTONOMOUS_RUN_COMPLETE.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(document)
    assert marker.artifact_digest == document["artifact_digest"]


def test_completion_cannot_be_complete_without_processed_source_data() -> None:
    inputs = replace(fixture_inputs_with_failures(), execution_status="complete", failed_slides_count=0)
    with pytest.raises(ValueError, match="source data"):
        build_final_report(inputs)
