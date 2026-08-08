# Limitations

- The storage-feasible reduced cohort was not processed because measured full-grid execution remains multi-day under the resource-aware two-worker limit.
- Only one development-partition source was downloaded and checksum-verified for eligibility and throughput calibration.
- Public catalog fixtures were verified for reader conformance only and were excluded from all scientific partitions.
- No pilot, tuning, freeze, or final compression outcome was observed; no compression-performance inference is available.
- Four host-only native-codec checks were structurally skipped; all 32 relevant codec and method tests passed inside the pinned container.
