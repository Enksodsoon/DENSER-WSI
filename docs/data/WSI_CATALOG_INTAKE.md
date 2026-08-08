# WSI Catalog Intake

## Scope

The user-supplied catalog package was inspected as untrusted discovery input on
2026-08-08. Its download script was not executed. The CSV contains 263 rows:
255 direct file URLs and 8 directory URLs across 21 format families. Only 75
rows name a checksum authority; 188 do not.

The package is useful for reader conformance and later secondary robustness
testing. It is not a substitute for the frozen, case-disjoint TCGA design:
entries include encoding variants, cropped samples, metadata, bulk manifests,
and samples without independently resolved checksums.

## Admission rule

A catalog item may be admitted only when all of the following hold:

1. it is a direct file rather than a directory listing;
2. exact bytes and SHA-256 are resolved from an authoritative source;
3. the downloaded bytes match both values;
4. archive extraction passes traversal checks when applicable; and
5. the resulting fixture is permanently marked `non_primary_conformance` and
   `primary_experiment_eligible=false`.

This rule is enforced by `denser.data.catalog`, not only by documentation.
Catalog samples cannot enter development, pilot, tuning, or final partitions.

## Verified intake

Three small, checksum-backed OpenSlide fixtures were admitted privately: two
Aperio-family files exercising conventional and JPEG 2000 decoding, plus one
multi-file MIRAX archive. The pinned OpenSlide 4.0.1 container successfully
opened all three after byte/hash verification and safe extraction.

No WSI, source checksum, private manifest, local path, or per-slide result is
stored in this public repository.

## Catalog package provenance

The six supplied package artifacts were hashed before inspection:

| Artifact | SHA-256 |
|---|---|
| Full aria2 manifest | `f8c939093cbad41fab2b30c6bf666a3abd3f3c5aad40879a80368546030e7035` |
| Starter aria2 manifest | `d4d661a4ffa33649197826e25c8c9246a14c1cf79d080765fcdd2b94a9c05a63` |
| Direct-download CSV | `d077dfddf9b1331957eeb6a3f31b9d61989b8fbec9cb808080a865a27fc966d6` |
| Workbook | `08153ae0c5644a6966ce25e972b9e31f53a0395b8b9ee8fcd3d4d9640ee3c100` |
| Download shell script | `abfa84b2f24685d19aa7b3482259be05d59633c00a0b4af08434bb2a9f1f6116` |
| Catalog README | `e26d2fef78b79a575776b23c5a2bab94e3884e57a9a707ff52baaec4098639c3` |
