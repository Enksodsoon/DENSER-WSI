# Decision Log

## 2026-08-09 — Primary-scale calibration audit

- A pre-freeze audit found that the private calibration utility still admitted
  the earlier 0.10–1.00 micrometre-per-pixel development range even though the
  authoritative primary band is 0.20–0.30. The resulting calibration record is
  retired and cannot support a final freeze.
- Calibration, the development configuration, and verified real-tile
  benchmarking now fail closed outside 0.20–0.30. Ineligible slides are
  excluded from calibration before pixel outcomes are inspected and are
  recorded only by private ordinal and reason code.
- Strict-band exploratory reruns found 5/6 eligible development slides and 3/6
  eligible slides in each of pilot and tuning. All three phases are therefore
  `not_evaluable`; their sampled reductions are mechanism evidence only and are
  not whole-slide or confirmatory claims.
- HE-V1 calibration and all downstream sampled phases must be rerun from the
  corrected primary-band implementation before any automatic freeze.

## 2026-08-09 — Generation 1 archived before freeze

- A bounded random-access TIFF metadata preflight followed remote first-directory
  offsets and read 14,985 aggregate bytes across the sealed final partition. It
  decoded no pixels and inspected no compression outcomes.
- Fifteen of eighteen final sources were in the 0.20–0.30 micrometre-per-pixel
  primary band; three were at 0.5015. Generation 1 therefore cannot satisfy the
  predeclared minimum of 18 evaluable final slides and is classified
  `not_evaluable` before freeze.
- No final slide was compressed, no Generation 1 freeze was written, and no
  compression or novelty conclusion is drawn. The partially started source
  downloads remain private and resumable.
- The next generation must exclude every Generation 1 case and verify physical
  scale from bounded metadata reads before assigning partitions. This is a
  cohort-integrity correction, not a mechanism change or outcome-driven retune.

## 2026-08-09 — Generation 2 scale-prefiltered cohort

- The official query returned 10,468 open, released SVS slide records across
  the six primary projects. Candidate order was derived from a new private salt;
  physical-scale metadata was checked before partition assignment.
- Generation 2 contains 48 unique, case-disjoint sources: 6 development, 6
  pilot, 6 tuning, 18 final, and 12 prefrozen reserves. Each project contributes
  eight sources, every source is within 0.20–0.30 micrometres per pixel, and no
  case or file overlaps Generation 1.
- The selected sources total 22,516,188,238 bytes including reserves. The
  manifest and salt remain under the private run root. No compression outcome
  was inspected during selection.
- Generation 2 retains the source-segment composition hypothesis because
  Generation 1 was not evaluable for cohort metadata, not falsified on a final
  compression endpoint. It receives a fresh calibration, routing selection,
  sampled phases, freeze, and holdout; no Generation 1 final source may enter
  tuning or inference.

## 2026-08-09 — Generation 2 pre-outcome comparator and resume policy

- Before any Generation 2 pixel outcome was inspected, the exact project-routed
  standard policy selected on Generation 1 development data was copied forward
  byte-for-byte. Generation 2 cannot retune this policy; the full 12-profile
  ladder remains a development-only sensitivity analysis.
- The confirmatory methods are the routed standard comparator and the smaller
  of that accepted result or the self-contained source-segment composition.
  The retired uniform-DCT mechanism is not part of this generation.
- MC-V2 final writers now use freeze-bound append journals plus a shared
  multi-method checkpoint. Resume verifies packet digests, truncates work after
  the last shared checkpoint, and fails closed for mismatched freeze identity,
  partial finalization, or completion-marker tampering.
- The automatic freeze binds the full runtime tree, configurations, private
  manifest and reserves, calibration, routing, SBOM, container digest, and the
  predeclared novelty hypothesis. None of these records authorize a novelty
  claim before the technical and prior-art gates pass.

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
