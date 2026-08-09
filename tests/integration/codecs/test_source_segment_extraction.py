from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile

from denser.codecs.source_segments import (
    build_source_segment_candidate_from_svs,
    decode_source_segment_candidate,
)
from denser.core.models import TileAddress


def test_jpeg_source_segments_form_an_independently_decodable_exact_crop(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "synthetic.svs"
    rgb = np.arange(32 * 32 * 3, dtype=np.uint16).reshape(32, 32, 3)
    rgb = ((rgb * 37) % 256).astype(np.uint8)
    tifffile.imwrite(
        source_path,
        rgb,
        tile=(16, 16),
        compression="jpeg",
        compressionargs={"level": 90},
        photometric="rgb",
        metadata=None,
    )
    expected_canvas = tifffile.imread(source_path)

    candidate = build_source_segment_candidate_from_svs(
        source_path, TileAddress(0, 8, 8, 16, 16)
    )
    repeated = build_source_segment_candidate_from_svs(
        source_path, TileAddress(0, 8, 8, 16, 16)
    )
    decoded = decode_source_segment_candidate(
        candidate.payload, candidate.allocation_map, (16, 16, 3)
    )

    np.testing.assert_array_equal(decoded, expected_canvas[8:24, 8:24])
    assert repeated.payload == candidate.payload
    assert repeated.allocation_map == candidate.allocation_map
    assert candidate.complete_bytes == len(candidate.payload) + len(candidate.allocation_map)


def test_source_segment_extraction_rejects_non_level_zero_and_out_of_bounds(
    tmp_path: Path,
) -> None:
    import pytest

    source_path = tmp_path / "synthetic.svs"
    tifffile.imwrite(
        source_path,
        np.zeros((16, 16, 3), dtype=np.uint8),
        tile=(16, 16),
        compression="jpeg",
        photometric="rgb",
        metadata=None,
    )
    with pytest.raises(ValueError, match="level 0"):
        build_source_segment_candidate_from_svs(
            source_path, TileAddress(1, 0, 0, 8, 8)
        )
    with pytest.raises(ValueError, match="bounds"):
        build_source_segment_candidate_from_svs(
            source_path, TileAddress(0, 12, 12, 8, 8)
        )
