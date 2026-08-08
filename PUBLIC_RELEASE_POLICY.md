# Public Release Policy

Public Git may contain source code, synthetic fixtures, specifications, tests,
schemas, CI, SBOMs, tool/configuration digests, aggregate statistics, plots,
limitations, and standalone compatibility findings.

Public Git must exclude raw or derived slide payloads, source-linked metadata,
private manifests, salts, identifiers, coordinates, source hashes, signed URLs,
absolute local paths, detailed tables, per-slide rows, and aggregate cells with
fewer than five observations. Real-data GitHub Actions artifacts are prohibited.

Every proposed push must pass the local public-release scanner. GitHub secret
scanning and push protection are additional controls, not substitutes.
