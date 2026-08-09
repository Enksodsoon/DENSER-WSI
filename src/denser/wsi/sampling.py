from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np

from denser.core.canonical import canonical_json_bytes
from denser.core.hashes import sha256_bytes
from denser.core.models import TileAddress
from denser.wsi.grid import iter_level0_grid


STRATA = ("low_tissue", "mixed_tissue", "high_tissue", "artifact_enriched")


class SamplingSlide(Protocol):
    level_dimensions: tuple[tuple[int, int], ...]

    def read_level0_region(self, address: TileAddress) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class SamplingConfig:
    tile_size: int
    samples_per_stratum: int

    def __post_init__(self) -> None:
        if self.tile_size <= 0 or self.samples_per_stratum <= 0:
            raise ValueError("sampling dimensions and counts must be positive")


@dataclass(frozen=True, slots=True)
class TileSample:
    address: TileAddress
    stratum: str
    tissue_fraction: float
    artifact_fraction: float


@dataclass(frozen=True, slots=True)
class TileSampleManifest:
    version: str
    seed: int
    tile_size: int
    rows: tuple[TileSample, ...]
    strata_counts: tuple[tuple[str, int], ...]
    sha256: str

    def _document(self, *, include_digest: bool) -> dict[str, object]:
        document: dict[str, object] = {
            "version": self.version,
            "seed": self.seed,
            "tile_size": self.tile_size,
            "rows": [
                {
                    "address": asdict(row.address),
                    "stratum": row.stratum,
                    "tissue_fraction": row.tissue_fraction,
                    "artifact_fraction": row.artifact_fraction,
                }
                for row in self.rows
            ],
            "strata_counts": dict(self.strata_counts),
        }
        if include_digest:
            document["sha256"] = self.sha256
        return document

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self._document(include_digest=True))


def measure_content(rgb: np.ndarray) -> tuple[float, float, str]:
    pixels = np.asarray(rgb)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("sampling requires canonical uint8 RGB pixels")
    channels = pixels.astype(np.int16)
    maximum = channels.max(axis=2)
    minimum = channels.min(axis=2)
    luminance = channels.mean(axis=2)
    tissue = (luminance < 235) & ((maximum - minimum) > 10)
    artifact = (maximum < 8) | ((maximum - minimum) > 220)
    tissue_fraction = round(float(tissue.mean()), 8)
    artifact_fraction = round(float(artifact.mean()), 8)
    if artifact_fraction >= 0.10:
        stratum = "artifact_enriched"
    elif tissue_fraction < 0.10:
        stratum = "low_tissue"
    elif tissue_fraction < 0.75:
        stratum = "mixed_tissue"
    else:
        stratum = "high_tissue"
    return tissue_fraction, artifact_fraction, stratum


def _selection_key(seed: int, sample: TileSample) -> str:
    address = sample.address
    return hashlib.sha256(
        f"{seed}\0{address.level}\0{address.x}\0{address.y}".encode("ascii")
    ).hexdigest()


def freeze_sample(
    slide: SamplingSlide, config: SamplingConfig, seed: int
) -> TileSampleManifest:
    width, height = slide.level_dimensions[0]
    candidates: dict[str, list[TileSample]] = {stratum: [] for stratum in STRATA}
    for address in iter_level0_grid(width, height, config.tile_size):
        tissue_fraction, artifact_fraction, stratum = measure_content(
            slide.read_level0_region(address)
        )
        candidates[stratum].append(
            TileSample(address, stratum, tissue_fraction, artifact_fraction)
        )
    selected: list[TileSample] = []
    strata_counts: list[tuple[str, int]] = []
    for stratum in STRATA:
        ordered = sorted(candidates[stratum], key=lambda row: _selection_key(seed, row))
        chosen = ordered[: config.samples_per_stratum]
        selected.extend(chosen)
        strata_counts.append((stratum, len(candidates[stratum])))
    unsigned = TileSampleManifest(
        "tile-sample-1",
        seed,
        config.tile_size,
        tuple(selected),
        tuple(strata_counts),
        "",
    )
    digest = sha256_bytes(canonical_json_bytes(unsigned._document(include_digest=False)))
    return TileSampleManifest(
        unsigned.version,
        unsigned.seed,
        unsigned.tile_size,
        unsigned.rows,
        unsigned.strata_counts,
        digest,
    )
