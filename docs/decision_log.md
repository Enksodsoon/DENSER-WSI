# Decision Log

## 2026-08-08 — Audited reconstruction

- Original ZIP and bundle unavailable; reconstruct from authenticated plan.
- Treat referenced commit as provenance only, not checked-out history.
- Public repository model: code plus aggregate reports, Apache-2.0.
- Private runtime root: `D:\DENSER-WSI-Run`.
- Public implementation branch: `codex/full-autonomous-research`; draft PR,
  no automatic merge.

## 2026-08-08 — Reduced-tier live execution classification

- The official GDC open/released SVS query returned 13,923 records across the ten
  declared primary and reserve projects. No source identifiers were persisted publicly.
- A salted, case-disjoint, six-project reduced cohort was frozen privately: 6 development,
  6 pilot, 6 tuning, and 18 final slides (36 total; 18,227,658,310 source bytes).
- Storage preflight passed. One frozen development source (910,049,677 bytes) was downloaded
  and admitted only after exact GDC MD5 and byte-count verification.
- That eligible source contained 28,224 level-0 512px tiles at 0.248 micrometres per pixel.
  A three-tile pinned-container benchmark measured mean per-tile times of 0.011 s read,
  0.544 s uniform, 1.532 s DENSER, and 0.716 s for the 12 standard candidates.
- The single-slide lower bound is about 22 CPU-hours, or 3.7 ideal wall-hours at the six-worker
  cap, before certificate, repair, and container overhead. The reduced real run is therefore
  classified `resource_limited`; scientific outcome is `not_evaluable`. No final holdout was
  opened or compressed, and no compression-performance conclusion is reported.

## 2026-08-08 — Catalog intake and bounded performance revision

- The supplied 263-row public WSI catalog was admitted as discovery metadata,
  not as an experimental cohort. Its supplied shell downloader was not run.
- Three independently checksum-resolved fixtures covering Aperio, JPEG 2000,
  and multi-file MIRAX decoding were downloaded into the private run root.
  Pinned OpenSlide 4.0.1 opened all three. They are permanently ineligible for
  primary development, pilot, tuning, and final partitions.
- Deterministic two-way candidate encoding, a process-wide two-codec semaphore,
  level-6 fixed-Huffman entropy coding with a new versioned entropy ID, and a
  row-run connected-component implementation reduced the measured three-tile
  verified path to about 1.13 wall-seconds per tile with two workers. Six
  workers oversubscribed this host, so the resource-aware limit is lowered to
  two for real execution.
- The measured development slide still projects to roughly 8.9 wall-hours.
  The run therefore remains `resource_limited` and scientifically
  `not_evaluable`; the final holdout remains unopened.

## 2026-08-08 — Breakthrough Generation 1 begins

- MC-V2 is introduced as a new, versioned research container while MC-V1 remains
  available for backward compatibility.
- Scientific-fidelity gaps were corrected before further real-data work: the
  final runner now defaults to the real frozen standard portfolio, candidate
  selection uses complete verified bytes, repair is serializable and
  certificate-bound, and a `complete` marker requires processed source data.
- The compact evidence-allocation map and JPEG XL quadtree families were both
  exercised on preliminary private development data. Neither passed the frozen
  HE-V1 pathway with a byte advantage, so no positive or novelty claim is made.
- The next Generation 1 step is development-only calibration using the declared
  benign and harmful controls. Pilot, tuning, freeze, and final remain unopened.
