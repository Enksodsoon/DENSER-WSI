# DENSER-WSI Audited Final Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and autonomously execute a reproducible, full-slide, contract-matched falsification study of evidence-sensitive H&E compression through a frozen final holdout and complete report.

**Architecture:** The project separates deterministic WSI input, MC-V1 storage, codec candidate portfolios, HE-V1 allocation/acceptance/audit evidence, DENSER quantization, repair/certification, checkpointed orchestration, and statistical reporting. Pilot and tuning use frozen sampled tiles; the final holdout encodes every level-0 tile into the same random-access container for DENSER and strong standard baselines.

**Tech Stack:** Python 3.12, NumPy, SciPy, Pillow, scikit-image, OpenSlide/libvips, pyarrow, pydantic, jsonschema, pytest, Hypothesis, Typer, psutil, zstandard, native JPEG/JPEG 2000 or HTJ2K/JPEG XL/AVIF command-line tools, Docker/OCI, SPDX SBOM.

## Global Constraints

- Repository visibility is private; never commit WSIs, extracted tissue, credentials, source identifiers, signed URLs, or absolute paths.
- Research only; H&E 8-bit bright-field scope; no clinical or diagnostic claim.
- No generative reconstruction in the primary method.
- Original source files are immutable and never overwritten.
- Use case-group-disjoint development, pilot, tuning, and final partitions.
- Use MC-V1 for every primary full-slide method comparison.
- Every lossy candidate, including standard codecs, must satisfy HE-V1 or use the same shared lossless fallback.
- Count every stored byte required to open, locate, verify, repair, and decode a slide.
- The final holdout is automatically frozen and run once; no manual unlock and no post-outcome retuning.
- The slide is the primary inferential unit; sampled tiles cannot support a whole-slide primary claim.
- Use strict red–green–refactor for production behavior.
- Commit each verified task locally; never push automatically.

---

## File map

```text
src/denser/
├── core/             immutable models, canonical JSON, hashes, errors
├── governance/       privacy, license, and resource preflight
├── toolchain/        native codec discovery, version capture, SBOM
├── data/             GDC resolver, manifests, case-disjoint partitioning
├── wsi/              source decoding, colour handling, grids, sampling
├── container/        MC-V1 writer, reader, index, byte ledger
├── codecs/           candidate wrappers, shared fallback, portfolios
├── evidence/         allocation, acceptance, audit, calibration
├── sensitivity/      JVP/sketch, singular spectrum, DNS
├── method/           DENSER candidate generation and quantization
├── repair/           union masks, escalation, exact overlays
├── certificates/     self-verifying reference payload and verification
├── orchestration/    checkpoints, retries, resources, phase runner
├── experiments/      development, pilot, tuning, freeze, final, robustness
├── analysis/         slide statistics, confidence intervals, figures
├── adapter/          standalone MC-V1/PathLab compatibility demonstration
└── cli.py             stable command-line surface
```

---

### Task 1: Python foundation and immutable contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/denser/__init__.py`
- Create: `src/denser/core/models.py`
- Create: `src/denser/core/canonical.py`
- Create: `src/denser/core/hashes.py`
- Create: `src/denser/core/errors.py`
- Create: `tests/unit/core/test_models.py`
- Create: `tests/unit/core/test_canonical.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `canonical_json_bytes(value: object) -> bytes`
- Produces: `sha256_bytes(data: bytes) -> str`
- Produces: immutable `TileAddress`, `SlideIdentity`, `ByteBreakdown`, `MethodResult`

- [ ] **Step 1: Write failing immutable-model tests**

```python
from denser.core.models import ByteBreakdown, TileAddress


def test_complete_bytes_is_exact_sum() -> None:
    value = ByteBreakdown(payload=10, repair=2, certificate=3, reference_evidence=4,
                          index=5, integrity=6, overview=7, metadata=8, padding=9)
    assert value.complete == 54


def test_tile_address_rejects_negative_coordinates() -> None:
    with pytest.raises(ValueError):
        TileAddress(level=0, x=-1, y=0, width=512, height=512)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/core -q`  
Expected: import failure for missing `denser.core` modules.

- [ ] **Step 3: Implement immutable models and canonical serialization**

Use frozen dataclasses or frozen Pydantic models. Canonical JSON must sort keys, use UTF-8, prohibit NaN/Infinity, and use compact separators.

```python
def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
```

- [ ] **Step 4: Run focused and full checks**

```bash
python -m pytest tests/unit/core -q
python -m compileall -q src tests
python scripts/validate_package.py
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests .github/workflows/ci.yml
git commit -m "build: establish deterministic Python research foundation"
```

---

### Task 2: Governance and execution preflight

**Files:**
- Create: `src/denser/governance/preflight.py`
- Create: `src/denser/governance/redaction.py`
- Create: `tests/unit/governance/test_preflight.py`
- Modify: `src/denser/cli.py`

**Interfaces:**
- Produces: `run_preflight(root: Path) -> PreflightReport`
- Produces: `redact_source_identifier(value: str, salt: bytes) -> str`

- [ ] **Step 1: Write failing tests for private-tree, path, and source-data checks**

```python
def test_preflight_rejects_wsi_in_repository(tmp_path: Path) -> None:
    (tmp_path / "patient.svs").write_bytes(b"x")
    report = run_preflight(tmp_path)
    assert "forbidden_source_payload" in report.error_codes


def test_redaction_is_deterministic_and_nonreversible() -> None:
    a = redact_source_identifier("GDC-file-id", b"0123456789abcdef")
    assert a == redact_source_identifier("GDC-file-id", b"0123456789abcdef")
    assert "GDC-file-id" not in a
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/governance -q`  
Expected: missing module failure.

- [ ] **Step 3: Implement fail-closed preflight**

Scan tracked and untracked repository paths for forbidden extensions, secrets, source IDs, and absolute paths. Verify configuration requires a private repository and prohibits clinical use. Produce machine-readable reason codes without logging sensitive values.

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/unit/governance -q
python -m denser.cli preflight --root .
```

- [ ] **Step 5: Commit**

```bash
git add src/denser/governance src/denser/cli.py tests/unit/governance
git commit -m "feat: add fail-closed research governance preflight"
```

---

### Task 3: Native toolchain, version pinning, and SBOM

**Files:**
- Create: `containers/research.Dockerfile`
- Create: `src/denser/toolchain/probe.py`
- Create: `src/denser/toolchain/sbom.py`
- Create: `tests/unit/toolchain/test_probe.py`
- Create: `tests/integration/toolchain/test_native_codecs.py`

**Interfaces:**
- Produces: `probe_toolchain() -> ToolchainReport`
- Produces: `write_sbom(report: ToolchainReport, output: Path) -> str`

- [ ] **Step 1: Write failing parser tests using recorded version strings**

```python
@pytest.mark.parametrize((text, expected), [
    ("cjxl v0.12.0", (0, 12, 0)),
    ("OpenJPEG version 2.5.3", (2, 5, 3)),
])
def test_parse_native_version(text: str, expected: tuple[int, int, int]) -> None:
    assert parse_version(text) == expected
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/toolchain -q`

- [ ] **Step 3: Implement probes and pinned container build**

Probe exact executable path, version, build flags, and SHA-256. Require JPEG XL 0.12.0 or later when JXL participates. Generate SPDX JSON with Python and native dependencies. Container images must be recorded by immutable digest.

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/unit/toolchain -q
python -m pytest tests/integration/toolchain -q
python -m denser.cli toolchain-report --output reports/toolchain.json
```

Integration tests may skip an optional codec only with a structured reason; the final evaluator later enforces the minimum comparator count.

- [ ] **Step 5: Commit**

```bash
git add containers src/denser/toolchain tests/unit/toolchain tests/integration/toolchain
git commit -m "build: pin and attest native compression toolchain"
```

---

### Task 4: GDC resolver and immutable download records

**Files:**
- Create: `src/denser/data/gdc.py`
- Create: `src/denser/data/download.py`
- Create: `src/denser/data/models.py`
- Create: `tests/unit/data/test_gdc.py`
- Create: `tests/integration/data/test_gdc_open_query.py`

**Interfaces:**
- Produces: `query_open_he_slides(client: GdcClient, projects: tuple[str, ...]) -> list[GdcSlideRecord]`
- Produces: `download_verified(record: GdcSlideRecord, destination: Path) -> DownloadRecord`

- [ ] **Step 1: Write failing query-contract tests**

```python
def test_query_requires_open_released_slide_images() -> None:
    query = build_gdc_query(("TCGA-LUAD",))
    assert query.filters_access == "open"
    assert query.filters_state == "released"
    assert query.filters_data_type == "Slide Image"
    assert query.filters_format == "SVS"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/data/test_gdc.py -q`

- [ ] **Step 3: Implement bounded official-API client**

Use bounded retries, pagination, response-schema validation, and no credential path. Capture file UUID internally, project, case identifier, primary site, stain type, magnification/MPP when available, file size, MD5, release/version, and access class. Logs expose only random research IDs.

- [ ] **Step 4: Implement verified streaming download**

Write to a temporary file, stream hashes, verify source MD5, calculate SHA-256, fsync, then atomic rename. A mismatch quarantines the file and never enters a manifest.

- [ ] **Step 5: Verify**

```bash
python -m pytest tests/unit/data -q
python -m pytest tests/integration/data/test_gdc_open_query.py -q
```

- [ ] **Step 6: Commit**

```bash
git add src/denser/data tests/unit/data tests/integration/data
git commit -m "feat: resolve and verify open GDC pathology sources"
```

---

### Task 5: Case-disjoint manifest selection and reserve replacement

**Files:**
- Create: `src/denser/data/manifest.py`
- Create: `src/denser/data/partition.py`
- Create: `tests/unit/data/test_partition.py`
- Modify: `schemas/slide_manifest.schema.json`

**Interfaces:**
- Produces: `assign_partitions(records, plan, seed) -> PartitionManifest`
- Produces: `select_replacement(manifest, partition, reason_code) -> SlideRecord`

- [ ] **Step 1: Write leakage tests**

```python
def test_case_group_never_crosses_partitions() -> None:
    manifest = assign_partitions(records_with_two_files_same_case(), plan, 20260807)
    by_case: dict[str, set[str]] = defaultdict(set)
    for row in manifest.rows:
        by_case[row.case_group_sha256].add(row.partition)
    assert all(len(partitions) == 1 for partitions in by_case.values())


def test_replacement_comes_from_prefrozen_reserve() -> None:
    result = select_replacement(frozen_manifest(), "pilot", "decode_failure")
    assert result.replacement_rank == 1
    assert result.outcome_inspected is False
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/data/test_partition.py -q`

- [ ] **Step 3: Implement deterministic balanced assignment**

Hash case identifiers with a run salt, detect exact duplicates by SHA-256, create project-balanced partitions, and pre-shuffle a reserve list. Serialize the manifest canonically and record its digest before compression work.

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/unit/data/test_partition.py -q
python scripts/validate_package.py
```

- [ ] **Step 5: Commit**

```bash
git add src/denser/data/manifest.py src/denser/data/partition.py tests/unit/data/test_partition.py schemas/slide_manifest.schema.json
git commit -m "feat: freeze case-disjoint experiment manifests"
```

---

### Task 6: WSI decoding, ICC handling, and MPP validation

**Files:**
- Create: `src/denser/wsi/reader.py`
- Create: `src/denser/wsi/color.py`
- Create: `src/denser/wsi/metadata.py`
- Create: `tests/unit/wsi/test_color.py`
- Create: `tests/integration/wsi/test_reader.py`
- Create: `tests/fixtures/wsi/README.md`

**Interfaces:**
- Produces: `open_slide(path: Path) -> SlideReader`
- Produces: `SlideReader.read_level0_region(address: TileAddress) -> np.ndarray`
- Produces: `canonicalize_rgb(rgb, source_icc, policy) -> CanonicalRgb`

- [ ] **Step 1: Write failing tests for dimensions, edge tiles, alpha removal, and colour policy**

```python
def test_edge_region_is_exact_requested_shape(reader: SlideReader) -> None:
    tile = reader.read_level0_region(TileAddress(0, 990, 990, 34, 34))
    assert tile.shape == (34, 34, 3)
    assert tile.dtype == np.uint8
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/wsi tests/integration/wsi -q`

- [ ] **Step 3: Implement deterministic reader adapter**

Use OpenSlide/libvips without loading the complete slide. Capture source pyramid and codec metadata. Apply a pinned ICC conversion when valid; otherwise record `profile_missing` and use decoded RGB without silent enhancement. Reject non-H&E scope violations.

- [ ] **Step 4: Verify**

```bash
python -m pytest tests/unit/wsi -q
python -m pytest tests/integration/wsi -q
```

- [ ] **Step 5: Commit**

```bash
git add src/denser/wsi tests/unit/wsi tests/integration/wsi tests/fixtures/wsi
git commit -m "feat: add deterministic physical-scale WSI input layer"
```

---

### Task 7: Deterministic level-0 grid and stratified tile sampling

**Files:**
- Create: `src/denser/wsi/grid.py`
- Create: `src/denser/wsi/sampling.py`
- Create: `tests/unit/wsi/test_grid.py`
- Create: `tests/unit/wsi/test_sampling.py`

**Interfaces:**
- Produces: `iter_level0_grid(width, height, tile_size) -> Iterator[TileAddress]`
- Produces: `freeze_sample(slide, config, seed) -> TileSampleManifest`

- [ ] **Step 1: Write coverage and determinism tests**

```python
def test_grid_covers_each_pixel_exactly_once() -> None:
    grid = list(iter_level0_grid(1000, 700, 512))
    assert sum(t.width * t.height for t in grid) == 700_000
    assert len({(t.x, t.y) for t in grid}) == len(grid)


def test_sampling_is_frozen_before_codec_use() -> None:
    a = freeze_sample(fake_slide(), config, 7)
    b = freeze_sample(fake_slide(), config, 7)
    assert a.sha256 == b.sha256
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/wsi/test_grid.py tests/unit/wsi/test_sampling.py -q`

- [ ] **Step 3: Implement grid and sampling**

Sampling strata use only pre-encoding image-content measurements and include low, mixed, high tissue, and artifact-enriched tiles. Sampling is without replacement and coordinates are frozen before candidate encoding.

- [ ] **Step 4: Verify and commit**

```bash
python -m pytest tests/unit/wsi -q
git add src/denser/wsi tests/unit/wsi
git commit -m "feat: freeze complete grids and stratified tile samples"
```

---

### Task 8: MC-V1 writer, reader, index, and complete-byte ledger

**Files:**
- Create: `src/denser/container/mcv1.py`
- Create: `src/denser/container/index.py`
- Create: `src/denser/container/ledger.py`
- Create: `tests/unit/container/test_mcv1.py`
- Create: `tests/corruption/test_mcv1_corruption.py`
- Create: `schemas/matched_container.schema.json`

**Interfaces:**
- Produces: `McV1Writer.add_tile(address, packet, breakdown) -> None`
- Produces: `McV1Reader.read_tile(address) -> bytes`
- Produces: `McV1Reader.byte_ledger() -> SlideByteLedger`

- [ ] **Step 1: Write failing round-trip and byte-accounting tests**

```python
def test_complete_bytes_equals_file_size(tmp_path: Path) -> None:
    path = tmp_path / "slide.mcv1"
    write_small_container(path)
    ledger = McV1Reader(path).byte_ledger()
    assert ledger.complete_bytes == path.stat().st_size
    assert sum(ledger.categories.values()) == ledger.complete_bytes


def test_one_tile_read_does_not_read_unrelated_payloads(tmp_path: Path) -> None:
    reader = instrumented_reader(write_three_tile_container(tmp_path))
    reader.decode_tile(TileAddress(0, 512, 0, 512, 512))
    assert reader.payload_reads == [1]
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/container tests/corruption/test_mcv1_corruption.py -q`

- [ ] **Step 3: Implement deterministic format**

Use a fixed header, deterministic overview, contiguous packet region, sorted spatial index, per-packet SHA-256 or stronger cryptographic digest, index digest, and final manifest digest. Prohibit dependencies. Count reference evidence, repair, integrity, index, overview, metadata, and padding separately.

- [ ] **Step 4: Add corruption tests**

Flip payload, index, certificate, and length bytes; truncate at every structural boundary. The reader must reject invalid data without returning pixels.

- [ ] **Step 5: Verify and commit**

```bash
python -m pytest tests/unit/container tests/corruption -q
git add src/denser/container tests/unit/container tests/corruption schemas/matched_container.schema.json
git commit -m "feat: add deterministic random-access matched container"
```

---

### Task 9: Shared lossless fallback and codec adapter contract

**Files:**
- Create: `src/denser/codecs/base.py`
- Create: `src/denser/codecs/lossless.py`
- Create: `tests/unit/codecs/test_base.py`
- Create: `tests/unit/codecs/test_lossless.py`

**Interfaces:**
- Produces: `CodecCandidate.encode(rgb: np.ndarray) -> EncodedCandidate`
- Produces: `CodecCandidate.decode(payload: bytes, shape: tuple[int,int,3]) -> np.ndarray`
- Produces: `SharedLosslessCodec`

- [ ] **Step 1: Write failing exact-round-trip tests**

```python
@given(rgb=rgb_arrays(max_side=64))
def test_shared_fallback_is_pixel_exact(rgb: np.ndarray) -> None:
    encoded = SharedLosslessCodec().encode(rgb)
    decoded = SharedLosslessCodec().decode(encoded.payload, rgb.shape)
    np.testing.assert_array_equal(decoded, rgb)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/codecs/test_lossless.py -q`

- [ ] **Step 3: Implement fixed lossless fallback**

Use reversible colour transform plus pinned zstd parameters, or a comparably deterministic lossless codec selected before pilot. Store all required decode parameters in the packet. Reject nondeterministic outputs.

- [ ] **Step 4: Verify and commit**

```bash
python -m pytest tests/unit/codecs -q
git add src/denser/codecs tests/unit/codecs
git commit -m "feat: establish shared pixel-exact fallback"
```

---

### Task 10: Standard codec wrappers and frozen candidate ladders

**Files:**
- Create: `src/denser/codecs/subprocess_codec.py`
- Create: `src/denser/codecs/jpeg.py`
- Create: `src/denser/codecs/jpeg2000.py`
- Create: `src/denser/codecs/jpegxl.py`
- Create: `src/denser/codecs/avif.py`
- Create: `tests/unit/codecs/test_commands.py`
- Create: `tests/integration/codecs/test_roundtrip.py`

**Interfaces:**
- Produces: `build_standard_candidates(rgb, ladder) -> list[EncodedCandidate]`

- [ ] **Step 1: Write command-construction tests**

```python
def test_jpeg_command_forces_444_and_disables_metadata(tmp_path: Path) -> None:
    cmd = JpegCodec(quality=75).encode_command(tmp_path / "in.ppm", tmp_path / "out.jpg")
    assert "4:4:4" in " ".join(cmd)
    assert "75" in cmd
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/codecs/test_commands.py -q`

- [ ] **Step 3: Implement safe wrappers**

Use argument arrays, bounded timeouts, isolated temporary directories, input/output size limits, captured stderr with path redaction, and no shell invocation. Verify decoded shape and dtype. Record exact executable hash/version with each result.

- [ ] **Step 4: Verify native round trips**

```bash
python -m pytest tests/integration/codecs/test_roundtrip.py -q
```

Each available codec must successfully encode and decode deterministic golden fixtures; unavailable optional codecs produce a structured skip reason.

- [ ] **Step 5: Commit**

```bash
git add src/denser/codecs tests/unit/codecs tests/integration/codecs
git commit -m "feat: add pinned independent standard codec candidates"
```

---

### Task 11: Allocation evidence operators

**Files:**
- Create: `src/denser/evidence/types.py`
- Create: `src/denser/evidence/stain.py`
- Create: `src/denser/evidence/boundary.py`
- Create: `src/denser/evidence/chromatin.py`
- Create: `tests/unit/evidence/test_allocation.py`

**Interfaces:**
- Produces: `compute_allocation_features(rgb, physical_grid, contract) -> AllocationEvidence`
- Produces: `allocation_jvp(rgb, vector, contract) -> np.ndarray`

- [ ] **Step 1: Write invariance and sensitivity tests**

```python
def test_chromatin_energy_detects_high_frequency_removal() -> None:
    original = synthetic_nuclei_texture()
    blurred = gaussian_blur(original, sigma=2.0)
    assert chromatin_distance(original, blurred) > 0.2


def test_allocation_features_are_deterministic() -> None:
    a = compute_allocation_features(fixture_rgb(), grid(), contract())
    b = compute_allocation_features(fixture_rgb(), grid(), contract())
    assert a.sha256 == b.sha256
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/evidence/test_allocation.py -q`

- [ ] **Step 3: Implement fixed differentiable operators**

Use optical-density transforms with bounded inputs, multiscale oriented gradients, and predeclared chromatin frequency bands. Avoid learned weights in HE-V1 allocation version 1.

- [ ] **Step 4: Verify and commit**

```bash
python -m pytest tests/unit/evidence/test_allocation.py -q
git add src/denser/evidence tests/unit/evidence/test_allocation.py
git commit -m "feat: implement HE-V1 allocation evidence"
```

---

### Task 12: Acceptance and audit-only evidence

**Files:**
- Create: `src/denser/evidence/nuclei.py`
- Create: `src/denser/evidence/architecture.py`
- Create: `src/denser/evidence/sentinels.py`
- Create: `src/denser/evidence/visual.py`
- Create: `src/denser/evidence/audit.py`
- Create: `tests/unit/evidence/test_acceptance.py`
- Create: `tests/unit/evidence/test_audit_separation.py`

**Interfaces:**
- Produces: `compute_acceptance_evidence(rgb, physical_grid, contract) -> AcceptanceEvidence`
- Produces: `compute_audit_evidence(rgb, audit_profile) -> AuditEvidence`

- [ ] **Step 1: Write tests that harmful controls fail applicable groups**

```python
@pytest.mark.parametrize("control,group", [
    ("delete_small_dark_object", "rare_event_sentinels"),
    ("shift_nuclear_boundary", "nuclear_objects"),
    ("collapse_lumen", "architecture"),
])
def test_harmful_control_is_detected(control: str, group: str) -> None:
    source, altered = challenge_pair(control)
    result = compare_acceptance(source, altered, frozen_contract())
    assert group in result.failed_groups
```

- [ ] **Step 2: Write an audit-separation test**

```python
def test_audit_features_cannot_enter_candidate_selection() -> None:
    assert "audit" not in inspect.signature(select_candidate).parameters
    assert "audit" not in inspect.signature(build_repair_mask).parameters
```

- [ ] **Step 3: Verify RED and implement**

Run: `python -m pytest tests/unit/evidence -q`

Implement deterministic nucleus/architecture/sentinel/visual measurements. Keep audit-only results in a separate type and package with no import path into allocation, repair, or profile-selection modules.

- [ ] **Step 4: Verify and commit**

```bash
python -m pytest tests/unit/evidence -q
git add src/denser/evidence tests/unit/evidence
git commit -m "feat: separate HE-V1 acceptance and withheld audit evidence"
```

---

### Task 13: Evidence calibration with family-wise controls

**Files:**
- Create: `src/denser/evidence/controls.py`
- Create: `src/denser/evidence/calibrate.py`
- Create: `tests/unit/evidence/test_calibration.py`
- Create: `schemas/calibration_record.schema.json`

**Interfaces:**
- Produces: `calibrate_contract(development_pairs, profile) -> CalibrationRecord`
- Produces: `verify_calibration(record, challenge_pairs) -> CalibrationAudit`

- [ ] **Step 1: Write tests preventing per-cell multiplicity leakage**

```python
def test_calibration_uses_tile_level_max_statistic() -> None:
    record = calibrate_contract(calibration_pairs(), profile())
    assert record.threshold_basis == "tile_familywise_max"


def test_challenge_controls_are_not_used_to_fit_thresholds() -> None:
    record = calibrate_contract(calibration_pairs(), profile())
    assert set(record.fit_control_ids).isdisjoint(record.challenge_control_ids)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/unit/evidence/test_calibration.py -q`

- [ ] **Step 3: Implement calibration**

Use development tiles only. Fit feature standardization and family-wise tile-level thresholds from benign controls. Evaluate harmful challenge controls separately. Refuse to freeze a contract if required harmful controls are undetected beyond predeclared limits; complete as not evaluable rather than silently loosening thresholds.

- [ ] **Step 4: Verify and commit**

```bash
python -m pytest tests/unit/evidence/test_calibration.py -q
git add src/denser/evidence/controls.py src/denser/evidence/calibrate.py tests/unit/evidence/test_calibration.py schemas/calibration_record.schema.json
git commit -m "feat: calibrate HE-V1 with family-wise challenge controls"
```

---

### Task 14: Contract-matched standard portfolio

**Files:**
- Create: `src/denser/codecs/portfolio.py`
- Create: `tests/unit/codecs/test_portfolio.py`

**Interfaces:**
- Produces: `select_standard_portfolio(rgb, candidates, verifier, fallback) -> MethodResult`

- [ ] **Step 1: Write smallest-passing-candidate tests**

```python
def test_standard_portfolio_chooses_smallest_verified_candidate() -> None:
    candidates = [candidate("q50", 100, False), candidate("q75", 140, True)]
    result = select_standard_portfolio(rgb(), candidates, verifier(), fallback())
    assert result.profile_id == "q75"
    assert result.breakdown.complete == 140 + result.verification_overhead


def test_standard_portfolio_uses_shared_fallback_when_all_fail() -> None:
    result = select_standard_portfolio(rgb(), all_failing_candidates(), verifier(), fallback())
    assert result.status == "fallback"
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/unit/codecs/test_portfolio.py -q`

The verifier and certificate policy are identical in principle to DENSER. Count evidence-reference and verification bytes needed by the standard portfolio; do not grant DENSER unique safety overhead.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/unit/codecs -q
git add src/denser/codecs/portfolio.py tests/unit/codecs/test_portfolio.py
git commit -m "feat: build strong contract-matched standard portfolio"
```

---

### Task 15: Sensitivity sketches and Diagnostic Nullity Spectrum

**Files:**
- Create: `src/denser/sensitivity/jvp.py`
- Create: `src/denser/sensitivity/randomized.py`
- Create: `src/denser/sensitivity/dns.py`
- Create: `tests/unit/sensitivity/test_spectrum.py`

**Interfaces:**
- Produces: `estimate_spectrum(operator, basis, seed, rank) -> SensitivitySpectrum`
- Produces: `diagnostic_nullity_spectrum(singular_values, thresholds) -> dict[float, float]`

- [ ] **Step 1: Write analytic-matrix recovery tests**

```python
def test_randomized_spectrum_recovers_known_rank() -> None:
    matrix = np.diag([5.0, 2.0, 0.0, 0.0])
    spectrum = estimate_spectrum(linear_operator(matrix), identity_basis(4), seed=7, rank=4)
    np.testing.assert_allclose(spectrum.values, [5.0, 2.0, 0.0, 0.0], atol=1e-6)
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/unit/sensitivity -q`

Use JVP/VJP interfaces and randomized SVD. Store approximation error, seed, rank, and convergence diagnostics. Never label DNS a diagnostic guarantee.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/unit/sensitivity -q
git add src/denser/sensitivity tests/unit/sensitivity
git commit -m "feat: estimate evidence sensitivity and nullity spectrum"
```

---

### Task 16: Uniform same-coder and DENSER candidate generation

**Files:**
- Create: `src/denser/method/transform.py`
- Create: `src/denser/method/quantize.py`
- Create: `src/denser/method/candidates.py`
- Create: `tests/unit/method/test_quantize.py`
- Create: `tests/unit/method/test_comparator.py`

**Interfaces:**
- Produces: `build_uniform_candidates(rgb, profile) -> list[EncodedCandidate]`
- Produces: `build_denser_candidates(rgb, sensitivity, profile) -> list[EncodedCandidate]`

- [ ] **Step 1: Write matched-comparator tests**

```python
def test_uniform_and_denser_share_basis_entropy_and_candidate_count() -> None:
    uniform = build_uniform_candidates(rgb(), profile())
    denser = build_denser_candidates(rgb(), sensitivity(), profile())
    assert [c.basis_id for c in uniform] == [c.basis_id for c in denser]
    assert [c.entropy_model_id for c in uniform] == [c.entropy_model_id for c in denser]
    assert len(uniform) == len(denser)
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/unit/method -q`

Use the frozen transform and entropy model for both portfolios. DENSER quantization follows sensitivity-weighted distortion budgets and trust-region caps. Uniform uses the same total candidate ladder without evidence weighting.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/unit/method -q
git add src/denser/method tests/unit/method
git commit -m "feat: implement matched uniform and evidence-sensitive candidates"
```

---

### Task 17: Union repair masks and deterministic escalation

**Files:**
- Create: `src/denser/repair/mask.py`
- Create: `src/denser/repair/escalate.py`
- Create: `src/denser/repair/residual.py`
- Create: `tests/unit/repair/test_mask.py`
- Create: `tests/unit/repair/test_escalation.py`

**Interfaces:**
- Produces: `build_union_repair_mask(failures, halo_um, mpp) -> RepairMask`
- Produces: `repair_until_verified(source, proposal, verifier, fallback) -> RepairResult`

- [ ] **Step 1: Write overlap and fallback tests**

```python
def test_overlapping_failed_cells_are_encoded_once() -> None:
    mask = build_union_repair_mask(overlapping_failures(), halo_um=2.0, mpp=0.25)
    assert mask.pixel_count < sum(f.pixel_count for f in overlapping_failures())


def test_unresolved_repair_fails_closed_to_lossless() -> None:
    result = repair_until_verified(source(), proposal(), always_fail_verifier(), fallback())
    assert result.status == "fallback"
    np.testing.assert_array_equal(result.decoded, source())
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/unit/repair -q`

Escalate through the four frozen stages. Count mask, overlay, residual, and signaling bytes. Compare total candidate size with the shared fallback before selection.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/unit/repair -q
git add src/denser/repair tests/unit/repair
git commit -m "feat: add sparse union repair with lossless fail-closed fallback"
```

---

### Task 18: Self-verifying evidence certificates

**Files:**
- Create: `src/denser/certificates/models.py`
- Create: `src/denser/certificates/encode.py`
- Create: `src/denser/certificates/verify.py`
- Create: `tests/unit/certificates/test_certificate.py`
- Create: `tests/corruption/test_certificate_tampering.py`
- Modify: `schemas/evidence_certificate.schema.json`

**Interfaces:**
- Produces: `build_reference_payload(source_evidence, quantization) -> ReferenceEvidencePayload`
- Produces: `verify_certificate(decoded_rgb, certificate, contract) -> VerificationResult`

- [ ] **Step 1: Write independent-verification test**

```python
def test_certificate_verifies_without_original_pixels() -> None:
    cert = build_certificate(source_rgb(), accepted_candidate(), contract())
    decoded = decode_candidate(accepted_candidate())
    result = verify_certificate(decoded, cert, contract())
    assert result.passed
    assert result.original_pixels_required is False
```

- [ ] **Step 2: Write digest-only limitation test**

```python
def test_digest_only_certificate_is_not_marked_self_verifying() -> None:
    cert = digest_only_certificate()
    assert cert.mode == "attested_digest"
    assert cert.self_verifying is False
```

- [ ] **Step 3: Verify RED and implement**

Run: `python -m pytest tests/unit/certificates tests/corruption/test_certificate_tampering.py -q`

Quantize the reference evidence with explicit bounded error. During comparison, combine reference quantization error with acceptance tolerance conservatively. Tampered payloads, contract digests, or packet hashes must fail closed.

- [ ] **Step 4: Verify and commit**

```bash
python -m pytest tests/unit/certificates tests/corruption -q
git add src/denser/certificates tests/unit/certificates tests/corruption schemas/evidence_certificate.schema.json
git commit -m "feat: add decoder-verifiable HE-V1 certificates"
```

---

### Task 19: Resource estimator and checkpointed autonomous orchestrator

**Files:**
- Create: `src/denser/orchestration/resources.py`
- Create: `src/denser/orchestration/state.py`
- Create: `src/denser/orchestration/runner.py`
- Create: `tests/unit/orchestration/test_resources.py`
- Create: `tests/unit/orchestration/test_resume.py`
- Modify: `schemas/execution_state.schema.json`

**Interfaces:**
- Produces: `choose_execution_tier(resource_report, source_manifest, policy) -> TierDecision`
- Produces: `PhaseRunner.run_all() -> CompletionState`

- [ ] **Step 1: Write deterministic tier tests**

```python
def test_tier_uses_source_scratch_output_and_reserve() -> None:
    decision = choose_execution_tier(resources(free=2_000), manifest(source=500), policy())
    assert decision.required_bytes == 500 + decision.scratch + decision.outputs + decision.reserve


def test_tier_cannot_depend_on_compression_outcome() -> None:
    assert "observed_reduction" not in inspect.signature(choose_execution_tier).parameters
```

- [ ] **Step 2: Write crash/resume test**

```python
def test_resume_reexecutes_only_uncommitted_atomic_step(tmp_path: Path) -> None:
    runner = crashing_runner(tmp_path, crash_after="wsi_io:3")
    with pytest.raises(SimulatedCrash):
        runner.run_all()
    resumed = runner.resume()
    assert resumed.repeated_steps == ["wsi_io:3"]
```

- [ ] **Step 3: Verify RED and implement**

Run: `python -m pytest tests/unit/orchestration -q`

Write state via temporary file, fsync, atomic rename, and sidecar digest. Verify hashes on resume. Implement bounded retries and phase-level commits. Place this orchestrator before any real experimental run.

- [ ] **Step 4: Verify and commit**

```bash
python -m pytest tests/unit/orchestration -q
git add src/denser/orchestration tests/unit/orchestration schemas/execution_state.schema.json
git commit -m "feat: add resource-aware checkpointed autonomous execution"
```

---

### Task 20: Synthetic full-pipeline validation

**Files:**
- Create: `src/denser/synthetic/histology.py`
- Create: `src/denser/experiments/synthetic.py`
- Create: `tests/integration/test_synthetic_pipeline.py`
- Create: `tests/golden/README.md`

**Interfaces:**
- Produces: `generate_synthetic_slide(spec, seed) -> SyntheticSlide`
- Produces: `run_synthetic_validation(config) -> SyntheticValidationReport`

- [ ] **Step 1: Write end-to-end failing test**

```python
def test_synthetic_slide_runs_all_portfolios_into_mcv1(tmp_path: Path) -> None:
    report = run_synthetic_validation(small_config(tmp_path))
    assert report.methods == {"standard", "uniform", "denser"}
    assert all(row.complete_bytes == row.path.stat().st_size for row in report.slides)
    assert report.unresolved_acceptance_violations == 0
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/integration/test_synthetic_pipeline.py -q`

Generate deterministic nuclei, glands, stroma, blank regions, rare dark objects, and known perturbations. Exercise every byte category, fallback, certificate, corruption, and resume path.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/integration/test_synthetic_pipeline.py -q
python -m pytest -q
git add src/denser/synthetic src/denser/experiments/synthetic.py tests/integration tests/golden
git commit -m "test: validate complete DENSER pipeline on synthetic slides"
```

---

### Task 21: Real development calibration run

**Files:**
- Create: `src/denser/experiments/development.py`
- Create: `tests/integration/experiments/test_development.py`
- Create at runtime: `reports/development/calibration-record.json`
- Create at runtime: `reports/development/candidate-screening.parquet`

**Interfaces:**
- Produces: `run_development(config, manifest) -> DevelopmentReport`

- [ ] **Step 1: Write a manifest-bound dry-run test**

```python
def test_development_refuses_non_development_slide() -> None:
    with pytest.raises(PartitionViolation):
        run_development(config(), manifest_with_pilot_slide())
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/integration/experiments/test_development.py -q`

The real run calibrates HE-V1, measures scratch multipliers, screens but does not alter frozen candidate sets outside allowed ranges, validates MPP bands, and writes an immutable calibration digest.

- [ ] **Step 3: Execute, verify, and commit only code/configuration**

```bash
python -m denser.cli run development --config configs/experiment/development.json
python -m denser.cli verify-run reports/development/run-manifest.json
git add src/denser/experiments tests/integration/experiments configs docs/decision_log.md
git commit -m "exp: calibrate HE-V1 on disjoint development slides"
```

Do not commit downloaded slides or source-identifying reports.

---

### Task 22: Sampled pilot experiment

**Files:**
- Create: `src/denser/experiments/pilot.py`
- Create: `tests/integration/experiments/test_pilot.py`
- Create at runtime: `reports/pilot/pilot-report.json`

**Interfaces:**
- Produces: `run_pilot(config, manifest, calibration) -> PilotReport`

- [ ] **Step 1: Write scope and no-extrapolation tests**

```python
def test_pilot_report_is_sampled_scope_only() -> None:
    report = pilot_fixture_report()
    assert report.rate_scope == "sampled_tiles_only"
    assert report.whole_slide_reduction is None
```

- [ ] **Step 2: Verify RED and implement**

Run all frozen pilot samples through standard, uniform, and DENSER portfolios. Record DNS, repair fraction, complete sampled bytes, fallback fraction, and audit-neutral mechanism metrics. A threshold miss is classified and execution continues.

- [ ] **Step 3: Execute and verify**

```bash
python -m denser.cli run pilot --config configs/experiment/pilot.json
python -m denser.cli verify-run reports/pilot/run-manifest.json
```

- [ ] **Step 4: Commit**

```bash
git add src/denser/experiments/pilot.py tests/integration/experiments/test_pilot.py reports/pilot/*.json docs/decision_log.md
git commit -m "exp: complete sampled DENSER pilot"
```

Commit only redacted, source-safe reports.

---

### Task 23: Tuning and deterministic profile selection

**Files:**
- Create: `src/denser/experiments/tuning.py`
- Create: `src/denser/experiments/profile_selection.py`
- Create: `tests/unit/experiments/test_profile_selection.py`
- Create at runtime: `reports/tuning/selected-profile.json`

**Interfaces:**
- Produces: `select_profile(results, rule) -> SelectedProfile`

- [ ] **Step 1: Write deterministic selection tests**

```python
def test_selection_uses_only_passing_profiles_and_frozen_tiebreakers() -> None:
    selected = select_profile(profile_results(), selection_rule())
    assert selected.profile_id == "DENSER-P3"
    assert selected.reason == "lowest_complete_bytes_then_lower_fallback_fraction"


def test_audit_only_metrics_cannot_select_profile() -> None:
    assert "audit_results" not in inspect.signature(select_profile).parameters
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/unit/experiments/test_profile_selection.py -q`

Search only the predeclared parameter grid. Do not relax evidence tolerances. Preserve every failed profile in the result table. If no DENSER profile is competitive, freeze the safest smallest DENSER profile for negative evaluation and retain the standard portfolio as operational fallback.

- [ ] **Step 3: Execute and commit**

```bash
python -m denser.cli run tuning --config configs/experiment/tuning.json
python -m denser.cli verify-run reports/tuning/run-manifest.json
git add src/denser/experiments tests/unit/experiments reports/tuning/*.json docs/decision_log.md
git commit -m "exp: select frozen DENSER profile on disjoint tuning slides"
```

---

### Task 24: Automatic freeze record

**Files:**
- Create: `src/denser/experiments/freeze.py`
- Create: `tests/unit/experiments/test_freeze.py`
- Create: `schemas/freeze_record.schema.json`
- Create at runtime: `reports/final/freeze-record.json`

**Interfaces:**
- Produces: `create_freeze_record(context) -> FreezeRecord`
- Produces: `verify_freeze_record(record, context) -> None`

- [ ] **Step 1: Write immutability tests**

```python
def test_freeze_fails_on_dirty_tree() -> None:
    with pytest.raises(FreezeViolation):
        create_freeze_record(context(dirty_tree=True))


def test_final_runner_rejects_changed_profile_digest() -> None:
    record = valid_freeze_record()
    with pytest.raises(FreezeViolation):
        verify_freeze_record(record, context(profile_digest="0" * 64))
```

- [ ] **Step 2: Verify RED and implement**

Run: `python -m pytest tests/unit/experiments/test_freeze.py -q`

Capture every item in Section 13 of the design. Write canonical JSON, fsync, atomic rename, and SHA-256 sidecar. Commit the freeze record locally, then continue automatically.

- [ ] **Step 3: Create and verify freeze**

```bash
python -m denser.cli freeze-final --output reports/final/freeze-record.json
python -m denser.cli verify-freeze reports/final/freeze-record.json
git add reports/final/freeze-record.json reports/final/freeze-record.json.sha256
git commit -m "exp: freeze confirmatory DENSER holdout"
```

---

### Task 25: Full-slide final holdout

**Files:**
- Create: `src/denser/experiments/final.py`
- Create: `tests/integration/experiments/test_final.py`
- Modify: `schemas/slide_result.schema.json`
- Create at runtime: `reports/final/complete-byte-ledger.parquet`
- Create at runtime: `reports/final/slide-level-results.parquet`
- Create at runtime: `reports/final/tile-level-results.parquet`

**Interfaces:**
- Produces: `run_final_holdout(config, manifest, freeze) -> FinalHoldoutResult`

- [ ] **Step 1: Write full-grid and freeze tests**

```python
def test_final_encodes_every_level0_tile_once() -> None:
    result = run_final_holdout(small_config(), tiny_manifest(), valid_freeze())
    assert result.encoded_addresses == set(iter_level0_grid(1025, 513, 512))


def test_final_forbids_sample_extrapolation() -> None:
    assert not final_config().sampled_tile_extrapolation_for_primary_endpoint_allowed
```

- [ ] **Step 2: Verify RED and implement**

Run every final slide through the frozen standard, uniform, and DENSER portfolios. Build complete MC-V1 files, verify their file sizes against ledgers, perform independent random-tile checks, and never alter profiles after outcome observation.

- [ ] **Step 3: Execute and verify**

```bash
python -m denser.cli run final-holdout --config configs/experiment/final_holdout.json --freeze reports/final/freeze-record.json
python -m denser.cli verify-final-ledger reports/final/complete-byte-ledger.parquet
```

- [ ] **Step 4: Commit source-safe final records**

```bash
git add src/denser/experiments/final.py tests/integration/experiments/test_final.py schemas/slide_result.schema.json reports/final/*.json docs/decision_log.md
git commit -m "exp: complete frozen full-slide DENSER holdout"
```

Do not commit large MC-V1 files or source-derived tiles.

---

### Task 26: Robustness, corruption, and audit-only analysis

**Files:**
- Create: `src/denser/experiments/robustness.py`
- Create: `tests/integration/experiments/test_robustness.py`
- Create at runtime: `reports/robustness/robustness-results.parquet`

**Interfaces:**
- Produces: `run_robustness(config, frozen_results) -> RobustnessReport`

- [ ] **Step 1: Write primary-result immutability test**

```python
def test_robustness_cannot_modify_primary_results(tmp_path: Path) -> None:
    primary = immutable_primary_bundle(tmp_path)
    before = sha256_tree(primary)
    run_robustness(config(), primary)
    assert sha256_tree(primary) == before
```

- [ ] **Step 2: Implement robustness suite**

Evaluate alternate MPP/tile-size bands, cold/warm latency, scanner/project heterogeneity, optional external data, audit-only evidence, and corruption. Keep all analyses clearly secondary or exploratory.

- [ ] **Step 3: Execute and commit**

```bash
python -m denser.cli run robustness --config configs/experiment/robustness.json
python -m pytest tests/integration/experiments/test_robustness.py tests/corruption -q
git add src/denser/experiments/robustness.py tests/integration/experiments reports/robustness/*.json docs/decision_log.md
git commit -m "exp: complete DENSER robustness and withheld-evidence audit"
```

---

### Task 27: Slide-level statistics and outcome classification

**Files:**
- Create: `src/denser/analysis/statistics.py`
- Create: `src/denser/analysis/outcome.py`
- Create: `tests/unit/analysis/test_statistics.py`
- Create: `tests/unit/analysis/test_outcome.py`

**Interfaces:**
- Produces: `paired_slide_analysis(rows, config, seed) -> StatisticalResult`
- Produces: `classify_scientific_outcome(result, completeness) -> ScientificOutcome`

- [ ] **Step 1: Write inferential-unit and classification tests**

```python
def test_bootstrap_resamples_slides_not_tiles() -> None:
    result = paired_slide_analysis(three_slides_many_tiles(), config(), seed=9)
    assert result.bootstrap_unit == "slide"


def test_positive_requires_all_primary_conditions() -> None:
    outcome = classify_scientific_outcome(result(median=.20, lower=.08), complete())
    assert outcome == "positive"
    assert classify_scientific_outcome(result(median=.20, lower=.08), complete(violations=1)) != "positive"
```

- [ ] **Step 2: Verify RED and implement**

Use project-stratified bootstrap when possible, fixed seeds, paired slide data, and exact completion criteria. Separate scientific outcome from resource/access qualifiers.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/unit/analysis -q
git add src/denser/analysis tests/unit/analysis
git commit -m "feat: add prespecified slide-level DENSER inference"
```

---

### Task 28: Standalone integration adapter

**Files:**
- Create: `src/denser/adapter/service.py`
- Create: `src/denser/adapter/pathlab_contract.py`
- Create: `tests/integration/adapter/test_service.py`
- Create at runtime: `reports/final/standalone-integration-compatibility.md`

**Interfaces:**
- Produces: `get_slide_metadata(path: Path) -> AdapterMetadata`
- Produces: `get_tile(path: Path, address: TileAddress) -> VerifiedTileResponse`

- [ ] **Step 1: Write independent adapter test**

```python
def test_adapter_returns_verified_random_tile_without_source_wsi(tmp_path: Path) -> None:
    container = audited_fixture_container(tmp_path)
    response = get_tile(container, TileAddress(0, 0, 0, 512, 512))
    assert response.verification_passed
    assert response.source_wsi_accessed is False
```

- [ ] **Step 2: Verify RED and implement**

Implement a standalone library/service demonstration only. Do not modify PathLab repositories. Measure open, cold, and warm tile latency and document server/browser implications.

- [ ] **Step 3: Verify and commit**

```bash
python -m pytest tests/integration/adapter -q
git add src/denser/adapter tests/integration/adapter reports/final/standalone-integration-compatibility.md
git commit -m "feat: demonstrate standalone verified MC-V1 tile access"
```

---

### Task 29: Final reproducibility bundle and report

**Files:**
- Create: `src/denser/analysis/report.py`
- Create: `tests/integration/test_final_report.py`
- Modify: `schemas/completion_marker.schema.json`
- Create at runtime:
  - `reports/final/FINAL_REPORT.md`
  - `reports/final/final-report.json`
  - `reports/final/reproducibility-manifest.json`
  - `reports/final/AUTONOMOUS_RUN_COMPLETE.json`
  - `reports/final/limitations.md`
  - `reports/final/software-bill-of-materials.spdx.json`

**Interfaces:**
- Produces: `build_final_report(inputs) -> FinalReportBundle`

- [ ] **Step 1: Write report-completeness tests**

```python
def test_final_report_includes_negative_and_missing_results() -> None:
    report = build_final_report(fixture_inputs_with_failures())
    assert report.failed_slides_count == 2
    assert report.missing_comparators == ["avif"]
    assert report.vendor_source_endpoint_label == "descriptive_not_primary"


def test_completion_separates_execution_from_scientific_outcome() -> None:
    marker = report_fixture().completion_marker
    assert marker.execution_status in {"complete", "resource_limited", "external_access_limited"}
    assert marker.scientific_outcome in {"positive", "negative", "inconclusive", "not_evaluable"}
```

- [ ] **Step 2: Verify RED and implement**

Report all slides, fallbacks, larger candidates, codec omissions, threshold misses, contract failures, audit-only failures, resource qualifiers, and exact denominators. Include no source file IDs or patient/case identifiers.

- [ ] **Step 3: Run complete verification**

```bash
python -m denser.cli generate-final-report
python scripts/validate_package.py
python -m pytest -q
python -m compileall -q src tests scripts
git diff --check
git status --short
```

Expected: validator passes, all tests pass, compile succeeds, no diff whitespace errors, and only intentional final-report artifacts are uncommitted before the final commit.

- [ ] **Step 4: Commit and stop**

```bash
git add src/denser/analysis/report.py tests/integration/test_final_report.py schemas/completion_marker.schema.json reports/final docs/decision_log.md
git commit -m "report: publish complete autonomous DENSER research outcome"
```

The program ends after verifying the completion marker. Do not retune or rerun the frozen final analysis to improve the result.

---

## Final verification checklist

- [ ] Repository contains no WSI, tile, source ID, credential, signed URL, or absolute local path.
- [ ] Every primary final slide is case-disjoint and has a verified source checksum.
- [ ] Final freeze record matches code, configs, native tools, manifests, and analysis.
- [ ] Every method uses MC-V1 and the same overview/index/integrity policy.
- [ ] Standard portfolio and DENSER use the same HE-V1 acceptance logic and shared lossless fallback.
- [ ] Complete ledgers equal physical container sizes.
- [ ] Every level-0 final tile is encoded exactly once per method.
- [ ] No sampled bytes are extrapolated into the primary full-slide endpoint.
- [ ] Self-verifying certificates can be checked without source pixels.
- [ ] Audit-only evidence never influences allocation, repair, or profile selection.
- [ ] Primary inference uses slides, not tiles.
- [ ] Negative, larger, failed, missing, and substituted results are retained.
- [ ] Completion marker separates execution status from scientific outcome.
- [ ] No clinical, universal-preservation, patentability, or world-first claim is made.

---

## Final Codex instruction

```text
Read CODEX_START_HERE.md, AGENTS.md, AUTONOMOUS_EXECUTION.md, the full audit, the audited final design, the audited final implementation plan, and docs/plans/active/current.md.

Run the package validator and tests. Then execute every phase in configs/execution/autonomous.json in order using strict test-first development, atomic checkpoints, local phase commits, and no automatic pushes.

Continue automatically after every verified phase. Do not ask for manual authorization for any experiment phase. Create and verify the automatic scientific freeze, then immediately run the final holdout once. Do not retune after final outcomes are observed.

Use MC-V1 for primary full-slide comparisons. Apply the same HE-V1 acceptance contract and shared lossless fallback to DENSER and the frozen standard-codec portfolio. Count every stored byte. Never infer whole-slide storage from sampled tiles.

When a threshold fails, a method is larger, an optional codec or dataset is unavailable, or resources require a predeclared reduced tier, record the limitation and continue through the appropriate negative, inconclusive, not-evaluable, resource-limited, or access-limited pathway.

Stop only after all final artifacts and a valid AUTONOMOUS_RUN_COMPLETE.json exist, or after a fail-closed terminal integrity/data-governance incident has been documented.
```
