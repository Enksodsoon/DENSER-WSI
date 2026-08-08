from __future__ import annotations

from denser.toolchain.probe import ToolSpec, probe_tool


def test_missing_native_codec_has_structured_reason() -> None:
    record = probe_tool(ToolSpec("definitely-missing-denser-codec", ("--version",)))
    assert not record.available
    assert record.error_code == "executable_not_found"
    assert record.path is None


def test_probe_records_declared_build_flags() -> None:
    record = probe_tool(
        ToolSpec(
            "definitely-missing-denser-codec",
            ("--version",),
            build_flags=("EXAMPLE_FLAG=ON",),
        )
    )
    assert record.build_flags == ("EXAMPLE_FLAG=ON",)
