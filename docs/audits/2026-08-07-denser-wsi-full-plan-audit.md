# DENSER-WSI Full Plan Audit

**Audit date:** 2026-08-07  
**Audited package:** `0.2.0-autonomous-spec`  
**Disposition:** superseded by `0.3.0-audited-final`

## Executive verdict

The earlier package was safe enough to start scaffolding, but it was not yet capable of producing a scientifically valid end-to-end WSI-compression conclusion. Its internal validator checked autonomy flags and file presence more strongly than scientific validity. The revised package keeps uninterrupted Codex execution while repairing the experimental design.

## Critical findings and repairs

| Finding | Why it invalidated or weakened the run | Final repair |
|---|---|---|
| No implementation task actually ran the tuning partition | The plan jumped from pilot analysis to automatic freeze | Added an explicit tuning and profile-selection phase with frozen candidate rules |
| The autonomous orchestrator was scheduled after the real pilot and final holdout | Checkpointing and nonblocking failure behavior would not exist when first needed | Moved orchestration, resource detection, and resume testing before every real-data phase |
| Sampled tile bytes were treated as complete slide bytes | A 256- or 1024-tile sample cannot support a whole-slide storage claim | Pilot/tuning remain sampled; the confirmatory endpoint encodes every level-0 tile into a real matched container |
| No full-slide container or pyramid policy existed | Index, metadata, overview, random access, and container overhead were undefined | Added Matched Container MC-V1 used identically by DENSER and all standard baselines |
| “Strongest standard baseline” was undefined | A favorable or unfair comparator could be chosen after results | Added evidence-matched frozen baseline portfolios and a stronger verified-adaptive oracle comparator |
| Lossy baselines were not required to satisfy the same evidence contract | DENSER could be penalized for verification while standard codecs were not | Every lossy candidate is decoded, verified, escalated, or sent to the same lossless fallback |
| Certificate stored only evidence digests | A digest cannot independently verify evidence distance without the original evidence values | Primary mode now carries a counted self-verifying reference-evidence sketch; digest-only mode is an ablation and is not described as independently verifiable |
| No real development/calibration partition existed | Thresholds based only on synthetic/OpenSlide fixtures would not generalize | Added a case-disjoint real H&E development set before pilot |
| Calibration ignored thousands of local comparisons | A 99% per-cell pass rate would make almost every tile fail | Calibration is tile-family-wise using maximum group nonconformity; local scores still locate repairs |
| Calibration controls and final audit were circular | The same features could define, optimize, repair, and validate the codec | Added audit-only metrics and locked challenge controls that cannot influence allocation, repair, or profile selection |
| Partitions were disjoint only by file hash | Multiple slides from one case could leak across development, tuning, and holdout | Added case-group hash disjointness across all partitions |
| Physical scale was not controlled | A 32-pixel cell means different biology at 0.25 and 0.50 micrometers per pixel | Primary inference is restricted to a declared MPP band; kernels are defined in micrometers; other bands are robustness analyses |
| Original vendor-file comparison was treated like a matched endpoint | Vendor files contain different pyramids, labels, associated images, and metadata | Primary endpoint uses matched containers; vendor-file reduction is descriptive and reported separately |
| The 84-slide plan omitted development slides and was computationally incoherent | The final “slide” endpoint still sampled tiles while sweeping many codecs | Replaced with six-project balanced design: 12 development, 12 pilot, 12 tuning, and 30 complete-slide holdout images; optional external robustness is separate |
| Resource-tier selection had no deterministic sizing rule | Codex could download too much and exhaust storage mid-run | Added API-size preflight, scratch-reserve formulas, bounded retries, one-slide streaming, and explicit target/reduced/below-minimum tiers |
| Security policy conflicted with report requirements for slide identifiers | Reports required every slide while committed logs forbade all slide identifiers | Reports may use random research IDs; source UUIDs, case IDs, labels, and paths remain local-only |
| Package tests mainly asserted “continue automatically” | A package could pass while retaining the scientific defects above | Expanded validator/tests to enforce tuning, pre-pilot orchestration, full-slide final encoding, fair comparators, case disjointness, scale policy, certificate semantics, and endpoint definitions |

## Important but nonfatal improvements

- Added a required zstd-compressed RGB lossless fallback shared by every method.
- Required 8-bit 4:4:4 RGB for primary codec comparisons; chroma-subsampled results are secondary only.
- Added official GDC query fields, bounded retry behavior, official MD5 plus downloaded SHA-256, and data-release/version recording.
- Added container, slide-result, freeze-record, and completion-marker schemas.
- Added SBOM and native container digest capture.
- Added explicit cold/warm random-access latency and full-slide conversion-time measurements.
- Added exact repair-region unioning to prevent double counting overlapping halos.
- Added a final outcome `not_evaluable` pathway when required comparator, real data, or evidence calibration is insufficient.

## Scientific interpretation after repair

The revised experiment can establish only the following:

1. whether DENSER improves complete bytes over the same coder;
2. whether it improves a matched full-slide container over strong standard codecs under HE-V1;
3. how often repair and fallback are required;
4. whether audit-only metrics reveal degradation not caught by HE-V1;
5. conversion, decoding, memory, storage, and random-access costs.

It still cannot establish clinical noninferiority, all-task diagnostic preservation, patentability, or historical novelty.

## Audit conclusion

The final package is suitable for an autonomous falsification-first technical experiment. It contains no manual phase unlock. Automatic freeze remains mandatory because it protects the final holdout from retuning; it is a scientific integrity control, not a request for user approval.
