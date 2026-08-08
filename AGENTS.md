# Agent Instructions

- Execute `configs/execution/autonomous.json` in order.
- Use strict red-green-refactor for production behavior.
- Commit verified tasks locally. Push only after `scripts/check_public_release.py`
  and the package validator pass.
- Never commit WSI data, tiles, MC-V1 or MC-V2 containers, private manifests, salts,
  identifiers, coordinates, source hashes, signed URLs, absolute local paths,
  detailed Parquet rows, or cells with fewer than five observations.
- Do not weaken HE-V1, change partitions after outcomes, extrapolate sampled
  tiles into whole-slide claims, or retune after final-holdout observation.
- A negative, inconclusive, not-evaluable, resource-limited, or access-limited
  result is valid completion.
- Do not modify PathLab repositories. Integration is a standalone adapter only.
- Never claim this reconstruction checked out source commit
  `ad6e2b6286df4cd39bd7249f66a73dbc7ffae7bc`.
