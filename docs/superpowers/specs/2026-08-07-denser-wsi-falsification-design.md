# DENSER-WSI Audited Final Research Design

**Version:** 0.3.0-audited-final  
**Date:** 2026-08-07  
**Status:** Authoritative design for autonomous Codex execution  
**Repository:** Private research repository only

## 1. Purpose

DENSER-WSI is a falsification-first research program testing whether H&E whole-slide images can be compressed more efficiently by allocating distortion according to a declared pathology-evidence sensitivity model, verifying the decoded evidence, and repairing every detected contract violation before accepting a tile.

The program does not assume the central hypothesis is true. It is successful as an execution if it produces a reproducible positive, negative, inconclusive, or not-evaluable result with a complete byte ledger and transparent limitations.

## 2. Central empirical hypothesis

For an image tile \(x\), let \(F_A(x)\) be allocation features, \(F_V(x)\) be acceptance features, and \(F_Q(x)\) be audit-only features. DENSER proposes a decoded tile \(\hat{x}\) by quantizing preferentially along directions with low local sensitivity of \(F_A\). The tile is accepted only when every applicable acceptance test passes:

\[
 d_j(F_{V,j}(x),F_{V,j}(\hat{x})) \le \epsilon_j\quad\forall j.
\]

If a test fails, the encoder adds a deterministic repair layer and repeats verification. If verification still fails or repair is larger than the shared fallback, the tile uses the shared lossless fallback.

The falsifiable claim is:

> On real H&E slides, the accepted DENSER portfolio can use fewer complete bytes than a frozen portfolio of standard codecs subjected to the same acceptance contract, matched container, and lossless fallback.

## 3. Claims that are not made

The experiment cannot establish that:

- every possible diagnosis is preserved;
- every future pathology model is preserved;
- the HE-V1 evidence contract is clinically complete;
- the method is clinically noninferior;
- DENSER is patentable or historically unprecedented;
- a technical certificate is a regulatory or clinical certificate;
- a sampled-tile result is a whole-slide result.

## 4. Study architecture

The program has four distinct tracks.

### 4.1 Track A — Development and evidence calibration

Real development slides and deterministic synthetic controls are used to:

- standardize evidence features;
- calibrate tolerances and trust regions;
- verify that benign perturbations are not rejected excessively;
- verify that predeclared harmful controls are detected;
- screen fixed codec candidate ladders;
- validate physical-scale handling.

No primary compression endpoint is estimated from this track.

### 4.2 Track B — Sampled mechanism study

Pilot and tuning partitions use frozen, stratified tile samples. This track answers whether the proposed mechanism is promising and selects one DENSER profile before the final holdout.

It may report only sampled-tile endpoints. It may not extrapolate sampled bytes to a whole-slide result.

### 4.3 Track C — Confirmatory full-slide study

The final holdout encodes every level-0 tile into the same matched container for every method. The primary endpoint is slide-level complete-byte reduction versus the strongest frozen standard-codec portfolio that satisfies the same HE-V1 contract.

No tuning is permitted after final-outcome observation. The freeze is automatic and does not require human authorization.

### 4.4 Track D — Robustness and integration

After the primary analysis is immutable, the program evaluates:

- alternate MPP band;
- alternate tile sizes;
- scanner/project heterogeneity;
- audit-only evidence failures;
- packet corruption and truncation;
- cold and warm random-tile latency;
- optional external datasets;
- a standalone PathLab compatibility adapter.

## 5. Dataset design

### 5.1 Primary source

The primary autonomous source is open-access H&E pathology slides from the NCI Genomic Data Commons. Source discovery must use official API metadata, restrict access to open files, capture original MD5 and file-version metadata, and calculate a local SHA-256 after download.

### 5.2 Partitions

Target primary benchmark:

| Partition | Slides | Use |
|---|---:|---|
| Development | 12 | Evidence and candidate calibration |
| Pilot | 12 | Sampled mechanism assessment |
| Tuning | 12 | Frozen profile selection |
| Final holdout | 30 | Full-slide confirmatory endpoint |
| **Total** | **66** | Primary program |

The target design uses six projects, with 2 development, 2 pilot, 2 tuning, and 5 final slides per project when source availability permits. Thirty final slides follow an approximate paired-design calculation: for a 10-percentage-point effect, 15-percentage-point paired standard deviation, two-sided alpha 0.05, and 90% power, the normal approximation gives about 24 slides; 30 provides reserve for exclusions and heterogeneity. The final report must replace these planning assumptions with observed uncertainty.

Reduced design:

| Partition | Slides |
|---|---:|
| Development | 6 |
| Pilot | 6 |
| Tuning | 6 |
| Final holdout | 18 |

Below 18 final full slides, the primary endpoint is not conclusive and the run is reported as not evaluable or resource/access limited.

### 5.3 Leakage prevention

Partitions must be disjoint by:

- source file SHA-256;
- source file identifier;
- case-group hash derived from the source case identifier;
- duplicate/perceptual duplicate detection;
- replacement lineage.

A case may appear in only one partition. Replacements are selected from a pre-shuffled reserve list before any compression outcome for the rejected input is inspected.

### 5.4 Physical scale

Primary analysis includes slides with MPP in the 0.20–0.30 µm/pixel band. A 0.45–0.55 µm/pixel band is a prespecified robustness analysis. Unknown or inconsistent MPP slides may be described but cannot contribute to physical-scale evidence claims.

Evidence cells are specified in micrometres and converted to pixels per slide. The image itself remains at native resolution; no hidden resampling is permitted in the primary endpoint.

### 5.5 Optional external data

CAMELYON and PANDA may be used only when their access and use conditions are satisfied without bypassing authentication or automating terms acceptance. Their unavailability cannot block completion. They are robustness datasets, not substitutes chosen after primary outcomes are seen.

## 6. Input normalization

The primary image contract is:

- bright-field H&E;
- interleaved 8-bit RGB after deterministic source decoding;
- ICC-aware conversion to a pinned canonical sRGB profile when a valid source profile exists;
- explicit record when no profile exists;
- no chroma subsampling in the primary codec comparison;
- no generative restoration;
- no tissue deletion based solely on a tissue detector.

Associated images, labels, macros, proprietary metadata, and source pyramids are not silently mixed into the matched-container primary endpoint. Their source-file sizes are reported separately.

## 7. Matched Container V1 (MC-V1)

MC-V1 exists to make complete-byte comparisons fair and random-access compatible.

### 7.1 Contents

Every method stores exactly:

- every level-0 tile in a deterministic 512×512 grid, including edge tiles;
- one deterministic overview image common to all methods;
- spatial tile index;
- method metadata;
- integrity data;
- evidence certificate or verification metadata required by that method;
- repair payloads;
- fallback signaling;
- deterministic padding/alignment.

Intermediate pyramid levels are virtual and are not part of the primary storage endpoint.

### 7.2 Random access

Each tile must be independently decodable. Cross-tile prediction and dependencies are prohibited in MC-V1. A decoder must locate, validate, and decode one tile without reading unrelated tile payloads.

### 7.3 Complete-byte equation

For slide \(s\) and method \(m\):

\[
B_{s,m}=B_{payload}+B_{repair}+B_{certificate}+B_{reference\ evidence}+B_{index}+B_{integrity}+B_{overview}+B_{metadata}+B_{padding}.
\]

All terms are included. Temporary files and source WSIs are not counted in MC-V1, but peak scratch space is reported separately.

### 7.4 Source-file endpoint

Reduction versus the original vendor file is descriptive only because the vendor file may contain a different pyramid, associated images, and metadata. The primary endpoint compares MC-V1 against MC-V1.

## 8. Fair comparator architecture

### 8.1 Shared lossless fallback

Every candidate portfolio has access to the same independently decodable lossless RGB fallback. The exact fallback implementation and parameters are frozen before the pilot.

### 8.2 Standard-codec portfolio

The standard portfolio includes frozen candidate ladders for available required codecs, initially:

- JPEG 4:4:4;
- JPEG 2000 or HTJ2K;
- JPEG XL;
- AVIF or another pinned modern independent codec;
- shared lossless fallback.

For every tile, every candidate is decoded and evaluated with HE-V1. The standard portfolio selects the smallest candidate that passes all acceptance tests. If none passes, it uses the shared lossless fallback.

This contract-matched standard oracle is intentionally strong. DENSER must beat it to demonstrate practical benefit.

### 8.3 Mechanism comparator

The mechanism comparator uses the same transform, entropy coder, candidate count, MC-V1 container, certificate policy, and fallback as DENSER, but allocates distortion uniformly rather than by evidence sensitivity.

This isolates the contribution of evidence-guided allocation from the contribution of the underlying coder.

### 8.4 DENSER portfolio

The DENSER portfolio selects the smallest accepted candidate from a frozen DENSER candidate ladder. Candidate generation may differ in evidence-sensitive quantization and repair, but it receives no broader fallback or container advantage than the standard portfolio.

## 9. HE-V1 evidence contract

HE-V1 separates three classes of evidence.

### 9.1 Allocation features

Allocation features may influence the local sensitivity model and bit allocation:

- stain soft statistics;
- multiscale hematoxylin boundary spectrum;
- chromatin frequency spectrum.

They must be differentiable or have an explicitly defined generalized sensitivity approximation.

### 9.2 Acceptance features

Acceptance features determine pass/fail and repair:

- nuclear-object measurements;
- tissue architecture and topology;
- rare-event sentinels;
- human-visual floor;
- acceptance versions of stain, boundary, and chromatin measurements.

All applicable acceptance tests must pass after repair.

### 9.3 Audit-only features

Audit-only features are deliberately withheld from allocation, quantization, repair selection, and profile selection. They are calculated after the primary analysis to expose blind spots. They include fixed external embeddings and withheld morphology measurements.

An audit-only failure does not retroactively alter the primary endpoint. It must be reported prominently.

### 9.4 Calibration controls

Tolerances are calibrated on development data using:

- benign controls: deterministic decode/re-encode noise, small colour perturbation, and bounded scanner-like noise;
- harmful controls: nuclear-edge blur, chromatin-frequency removal, small-object deletion, boundary displacement, and local colour collapse.

The target is not a simplistic per-cell 99% acceptance rate. Thresholds are calibrated to a family-wise tile-level false-rejection target across all cells and acceptance groups, while retaining predefined harmful-control sensitivity.

Challenge controls are disjoint from controls used to choose thresholds.

### 9.5 Repair

Failed cells from all acceptance groups are combined into a union repair mask with a physical halo. Overlapping repairs are stored once. Repair escalation is deterministic:

1. finer local quantization;
2. local transform-coefficient overlay;
3. exact local pixel residual;
4. whole-tile shared lossless fallback.

The encoder accepts the smallest option that passes verification. If verification cannot be completed, it fails closed to the shared fallback.

## 10. Evidence certificates

### 10.1 Two certificate modes

- **Self-verifying certificate:** stores a compact, quantized reference-evidence payload sufficient for the decoder to recompute and compare every acceptance test without access to the original tile.
- **Attested digest:** stores only digests and is useful for provenance when a trusted encoder performed verification, but cannot independently prove the evidence bounds.

The primary DENSER endpoint requires the self-verifying mode. Digest-only certificates are an ablation and must not be called independently verifiable.

### 10.2 Certificate contents

A self-verifying tile certificate includes:

- contract and implementation digests;
- physical-scale metadata;
- quantized reference-evidence payload and error bounds;
- candidate and fallback identifiers;
- repair-region encoding;
- decoded evidence results;
- packet digest;
- verification status.

All certificate bytes count toward complete rate.

## 11. Sensitivity and Diagnostic Nullity Spectrum

For allocation features \(F_A\), transform basis \(\Phi\), and tile \(x\), DENSER estimates singular values of the local operator \(J_x\Phi\) using Jacobian-vector products and randomized methods rather than materializing a full Jacobian.

The exploratory Diagnostic Nullity Spectrum is:

\[
DNS_x(\tau)=\frac{1}{n}\#\{i:\sigma_i(J_x\Phi)\le\tau\}.
\]

DNS is an exploratory predictor, not proof of diagnostic safety. The final report tests whether DNS predicts accepted rate gain, repair fraction, and audit-only failures on unseen slides.

## 12. Experiment sequence

The autonomous sequence is:

1. foundation;
2. governance and resource preflight;
3. native toolchain and software bill of materials;
4. dataset resolution and case-disjoint manifests;
5. WSI decoding and physical-scale validation;
6. MC-V1 implementation;
7. standard baselines and shared fallback;
8. evidence-contract calibration machinery;
9. DENSER mechanism;
10. repair and certificates;
11. autonomous checkpoint/resume orchestrator;
12. synthetic end-to-end validation;
13. real development calibration;
14. pilot;
15. tuning and profile selection;
16. automatic freeze;
17. final full-slide holdout;
18. robustness and external audit;
19. statistical analysis;
20. standalone integration adapter;
21. final report.

Codex continues automatically after each verified phase. Threshold misses are recorded, not used as manual stops.

## 13. Automatic freeze

Before any final-holdout compression result is read, Codex writes an immutable freeze record containing:

- Git commit and clean-tree status;
- container image digest and SBOM digest;
- dependency and native-codec versions;
- complete configuration digest;
- partition and reserve-list digests;
- selected DENSER profile;
- frozen standard candidate ladders;
- evidence tolerances and implementation digest;
- analysis code digest;
- random seeds;
- expected final slide count.

The final runner verifies this record before every final slide. No human signature is required. Any post-freeze code or parameter change creates a new exploratory run and cannot replace the frozen primary analysis.

## 14. Statistical design

### 14.1 Primary endpoint

For final slide \(i\):

\[
R_i=1-\frac{B_{i,DENSER}}{B_{i,STANDARD}}.
\]

The primary estimand is the median \(R_i\) across slides. The standard denominator is the frozen contract-matched standard portfolio in MC-V1.

### 14.2 Success criterion

A positive technical result requires all of:

- at least 18 evaluable final full slides;
- at least two required standard codec families plus shared fallback;
- zero unresolved HE-V1 acceptance violations in accepted packets;
- independent random-tile decoding;
- median practical reduction at least 15%;
- project-stratified 95% bootstrap lower confidence bound greater than 5%.

### 14.3 Negative and inconclusive outcomes

- **Positive:** all success criteria pass.
- **Negative:** evaluable study with upper confidence bound at or below 5%, or DENSER is no smaller than the standard portfolio on the median slide.
- **Inconclusive:** evaluable study that is neither positive nor negative.
- **Not evaluable:** fewer than 18 final slides, fewer than two required standard codec families, invalid freeze, or incomplete primary byte ledger.

Resource and external-access limitations are recorded as qualifiers separate from scientific outcome.

### 14.4 Inference

- slide is the inferential unit;
- bootstrap is stratified by project when at least three projects are present;
- exact paired slide results are retained;
- secondary endpoints receive confidence intervals and multiplicity labels;
- tile-level observations are descriptive or hierarchical, not treated as independent slides;
- no sampled-tile extrapolation is used for the primary endpoint.

## 15. Performance and stability

Encoder wall time includes every candidate attempt, evidence calculation, verification pass, repair attempt, fallback decision, and container write. Decoder timing includes integrity and certificate verification. Search work may not be excluded merely because only the selected payload is stored.

Required measurements include:

- encode and decode throughput;
- peak RAM and scratch storage;
- cold random-tile latency;
- warm random-tile latency;
- container open/index time;
- deterministic rerun hashes;
- packet corruption and truncation behavior;
- certificate tampering behavior;
- recovery after interrupted run;
- DENSER-to-standard end-to-end encode-time ratio;
- DENSER-to-standard cold and warm decode-latency ratios.

Secondary deployability targets are DENSER median encode time no more than 10× the standard portfolio and p95 verified random-tile latency no more than 2× the standard portfolio on the same recorded hardware. Missing these targets does not alter the compression primary endpoint, but it prevents a deployability claim.

The decoder must fail closed on invalid index, digest, certificate, repair, or packet data.

## 16. Resource policy

Before download, Codex calculates the largest feasible predeclared tier using official source file sizes plus measured scratch multipliers from development fixtures. The estimate includes:

\[
D_{required}=D_{source}+D_{scratch}+D_{outputs}+D_{reports}+D_{reserve}.
\]

It selects the largest tier that fits without observing compression outcomes. A later downgrade must be caused by documented infrastructure failure, not method performance.

Processing is streaming and slide-concurrent work is bounded. Reproducible intermediates may be deleted only after their hashes and byte-ledger entries are durable.

## 17. Autonomous completion

The final completion marker separates execution status from scientific outcome:

- execution status: complete, resource-limited, external-access-limited, or terminal-integrity-failure;
- scientific outcome: positive, negative, inconclusive, or not-evaluable.

A negative result is a complete result. Codex does not retune after final outcomes to improve the conclusion.

## 18. PathLab boundary

The project may build a standalone adapter that demonstrates:

- MC-V1 metadata parsing;
- independent tile decoding;
- certificate verification;
- source/fallback selection;
- measured random-access latency;
- compatibility requirements for a future server integration.

It must not modify PathLab Viewer, Forge, or AI repositories during this program.

## 19. Required final artifacts

```text
reports/final/FINAL_REPORT.md
reports/final/final-report.json
reports/final/reproducibility-manifest.json
reports/final/AUTONOMOUS_RUN_COMPLETE.json
reports/final/complete-byte-ledger.parquet
reports/final/slide-level-results.parquet
reports/final/tile-level-results.parquet
reports/final/freeze-record.json
reports/final/limitations.md
reports/final/standalone-integration-compatibility.md
reports/final/software-bill-of-materials.spdx.json
```

## 20. Acceptance of this design

This design is authoritative. More detailed implementation choices may change only before the automatic freeze, must remain within the declared interfaces and scientific boundaries, and must be recorded in the decision log. Any material post-freeze change produces a separate exploratory analysis.
