from pathlib import Path

from denser.governance.run_layout import RunLayout
from scripts.preflight_private_partition_scale import scale_preflight_output


def test_scale_preflight_output_is_bound_to_requested_generation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = RunLayout(repo, tmp_path / "run")
    layout.ensure()
    output = scale_preflight_output(layout, "pilot", generation=2)
    assert output == layout.resolve(
        "results", "pilot", "generation-2", "scale-preflight.private.json"
    )
