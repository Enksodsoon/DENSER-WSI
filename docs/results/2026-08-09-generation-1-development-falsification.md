# Generation 1 development falsification

Date: 2026-08-09

Status: `not_evaluable` for the confirmatory endpoint; `resource_limited` at the development gate.

This note contains aggregate development results only. It contains no slide identifiers,
coordinates, source hashes, private paths, manifests, or per-slide rows. The aggregate cell
contains six case-disjoint development slides and therefore satisfies the public minimum-cell
policy.

## Frozen gate result

- Development slides represented: 6
- Deterministically sampled level-0 tiles: 6 (one per slide)
- Mean complete three-method tile pipeline time: 14.226 seconds
- P95 complete three-method tile pipeline time: 19.916 seconds
- Conservative reduced-confirmatory projection: 40.63 days
- Maximum permitted projection: 7 days
- Aggregate MC-V2-to-standard complete-byte ratio: 2.060
- Selected-packet unresolved HE-V1 violations: 0
- Independent packet verification: required and passing for every selected development packet
- Host reserve result: below the required 8 GiB at preflight

The development gate did not pass. Pilot, tuning, freeze, and final-holdout processing were not
started.

## Mechanisms falsified in development

Generation 1 evaluated compact evidence-conditioned DCT packets, evidence-guided JPEG XL
quadtree composition, increasingly conservative JPEG XL allocation policies, group-aware
composite repair, signed-delta exact repair, and block-local evidence-guided JPEG quadtree
composition. All retained calibrated HE-V1 without tolerance relaxation and used complete-byte
accounting. None produced a development result that was both smaller than the matched standard
portfolio and executable within the seven-day projection limit.

The quadtree families sometimes produced compact unverified base payloads. Their HE-V1 repair
payloads erased that advantage. This is a negative mechanism result, not evidence of diagnostic
equivalence for whole slides.

## Claim boundary

No compression breakthrough, novelty, clinical noninferiority, regulatory suitability, or
universal diagnostic-preservation claim is supported. A dated prior-art claim matrix was not
promoted to a novelty conclusion because the predeclared technical gate failed first.

The final cohort remains unopened. Resuming requires a new mechanism hypothesis plus a measured
resource plan that restores the 8 GiB host reserve and projects the complete reduced-confirmatory
run at no more than seven unattended days.
