from __future__ import annotations

from dataclasses import asdict

from denser.analysis.private_final import analyze_private_final_documents
from denser.experiments.final import FinalPerformanceSummary


def test_private_final_analysis_binds_manifest_order_to_container_ordinals() -> None:
    rows = [
        {
            "partition": "final",
            "project_id": f"P{index % 6}",
            "research_id": f"R{index:02d}",
        }
        for index in range(18)
    ]
    rows.reverse()
    ordered = sorted(rows, key=lambda row: (row["project_id"], row["research_id"]))
    containers = []
    for ordinal in range(18):
        for method, complete_bytes in (("standard", 1000), ("denser", 750)):
            containers.append(
                {
                    "method": method,
                    "path": f"/private/final-{ordinal:03d}.{method}.mcv2",
                    "complete_bytes": complete_bytes,
                    "tile_count": 100 + ordinal,
                }
            )
    performance = FinalPerformanceSummary(
        100.0, 400.0, 4.0,
        0.01, 0.015, 1.5,
        0.008, 0.009, 1.125,
        576,
    )
    result = analyze_private_final_documents(
        {
            "source_data_processed": True,
            "full_level0_grid": True,
            "slide_count": 18,
            "ledgers_match_files": True,
            "random_tiles_independently_decodable": True,
            "unresolved_acceptance_violations": 0,
            "performance": asdict(performance),
            "containers": containers,
        },
        {"rows": rows},
        {
            "routes": {
                f"P{index}": [
                    ("avif-q90", "jpegxl-d0.5", "jpeg2000-r4")[index % 3]
                ]
                for index in range(6)
            }
        },
        seed=20260808,
    )
    assert result.analysis.scientific_outcome == "positive"
    assert result.rows[0].slide_key == ordered[0]["research_id"]
    assert len(result.rows) == 18
