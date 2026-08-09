from __future__ import annotations

import argparse
from io import BytesIO
import json
import math
from pathlib import Path

import numpy as np

from denser.codecs.registry import build_default_registry
from denser.codecs.source_segments import build_source_segment_candidate_from_svs
from denser.codecs.source_segments import SourceSegmentAllocationV2
from denser.core.models import TileAddress
from denser.data.private_cohort import bind_verified_partition_sources
from denser.governance.run_layout import RunLayout
from denser.orchestration.runtime_projection import deterministic_sample_indices


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Private exactness check for self-contained MC-V2 source-segment tiles"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260808)
    arguments = parser.parse_args()
    layout = RunLayout(arguments.repo_root, arguments.run_root)
    sources = bind_verified_partition_sources(
        layout.resolve("manifests", "selected-sources.private.json"),
        layout,
        "development",
        expected_count=6,
    )
    registry = build_default_registry()
    results: list[dict[str, int | bool]] = []
    import openslide

    for slide_ordinal, source in enumerate(sources):
        import tifffile

        with tifffile.TiffFile(source.path) as source_tiff:
            source_page = source_tiff.pages[0]
            source_tags = {
                tag_name: str(source_page.tags[tag_name].value)
                for tag_name in (
                    "PhotometricInterpretation",
                    "YCbCrSubSampling",
                    "YCbCrCoefficients",
                    "ReferenceBlackWhite",
                )
                if tag_name in source_page.tags
            }
            source_tag_codes = [int(tag.code) for tag in source_page.tags.values()]
            source_description_header = str(source_page.description or "").split("|")[0]
        with openslide.OpenSlide(str(source.path)) as slide:
            width, height = slide.dimensions
            columns = math.ceil(width / 512)
            rows = math.ceil(height / 512)
            index = deterministic_sample_indices(
                columns * rows, 1, seed=arguments.seed, slide_ordinal=slide_ordinal
            )[0]
            tile_y, tile_x = divmod(index, columns)
            x, y = tile_x * 512, tile_y * 512
            tile_width = min(512, width - x)
            tile_height = min(512, height - y)
            address = TileAddress(0, x, y, tile_width, tile_height)
            expected = np.asarray(
                slide.read_region((x, y), 0, (tile_width, tile_height)).convert("RGB"),
                dtype=np.uint8,
            )
        candidate = build_source_segment_candidate_from_svs(source.path, address)
        with tifffile.TiffFile(BytesIO(candidate.payload)) as packet_tiff:
            packet_page = packet_tiff.pages[0]
            packet_tags = {
                tag_name: str(packet_page.tags[tag_name].value)
                for tag_name in ("PhotometricInterpretation", "YCbCrSubSampling")
                if tag_name in packet_page.tags
            }
            packet_tag_codes = [int(tag.code) for tag in packet_page.tags.values()]
        decoded = registry.decode(candidate, expected.shape)
        allocation = SourceSegmentAllocationV2.decode(candidate.allocation_map)
        delta = np.abs(decoded.astype(np.int16) - expected.astype(np.int16))
        results.append(
            {
                "exact": bool(np.array_equal(decoded, expected)),
                "decoder_code": allocation.decoder_code,
                "compression_code": allocation.compression_code,
                "maximum_channel_delta": int(delta.max(initial=0)),
                "mean_absolute_channel_delta_milli": int(round(float(delta.mean()) * 1000)),
                "expected_channel_means_milli": [
                    int(round(float(expected[:, :, channel].mean()) * 1000))
                    for channel in range(3)
                ],
                "decoded_channel_means_milli": [
                    int(round(float(decoded[:, :, channel].mean()) * 1000))
                    for channel in range(3)
                ],
                "source_tiff_tags": source_tags,
                "source_tiff_tag_codes": source_tag_codes,
                "source_description_header": source_description_header,
                "packet_tiff_tags": packet_tags,
                "packet_tiff_tag_codes": packet_tag_codes,
                "complete_bytes": candidate.complete_bytes,
            }
        )
    output = layout.resolve(
        "results", "development", "generation-1", "source-segment-validation.private.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "version": "DENSER-source-segment-private-validation-1",
                "source_data_processed": True,
                "all_exact": all(bool(row["exact"]) for row in results),
                "slides": results,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "development_slides": len(results),
                "all_exact": all(bool(row["exact"]) for row in results),
                "complete_bytes": sum(int(row["complete_bytes"]) for row in results),
            },
            sort_keys=True,
        )
    )
    return 0 if all(bool(row["exact"]) for row in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
