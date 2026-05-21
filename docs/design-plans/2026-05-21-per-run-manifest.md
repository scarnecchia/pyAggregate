# Per-Run Manifest Design

## Summary

pyAggregate processes and aggregates clinical study data across multiple runs, writing output as Parquet files organised by table name and output type (stacked, masked, rollup). Currently there is no durable record of what each run actually produced -- row counts, column schemas, and surrogate mapping size exist only in logs. This design adds a `manifest.json` written at the end of every successful or partially-failed run that captures exactly what landed on disk: per-table row counts, column names and Arrow types, and the surrogate count from the dpid_map.

The manifest is built entirely from post-write inspection of the run directory using `pyarrow.parquet.read_metadata()` to read Parquet file footers -- no data is scanned, and nothing is threaded through the pipeline. This keeps the manifest truthful by construction: it reflects what the disk contains, not what the pipeline intended to write. Both new functions (`collect_manifest` and `build_manifest_entry`) are pure, the output is sorted for determinism, and the file is written with the existing atomic temp-then-rename pattern already used throughout `writer.py`.

## Definition of Done

1. Every successful run produces a `manifest.json` in the run directory.
2. Manifest contains per-table row counts, column names, column types, and output types written.
3. Manifest includes dpid_map surrogate count.
4. Manifest structure is deterministic (diffable across runs).
5. Manifest is written atomically (temp-then-rename).
6. No changes to `pipeline.py` or `config.py`.

## Acceptance Criteria

### per-run-manifest.AC1: Manifest file produced
- **AC1.1 Success:** Every successful run (exit 0) produces `manifest.json` in the run directory
- **AC1.2 Success:** Partial failure runs (exit 2) also produce `manifest.json`
- **AC1.3 Success:** `manifest.json` is written atomically (temp-then-rename)
- **AC1.4 Edge:** Empty run (all tables skipped) produces manifest with empty `tables` object

### per-run-manifest.AC2: Per-table metadata
- **AC2.1 Success:** Each table entry lists all output types actually written (stacked, masked, rollup)
- **AC2.2 Success:** Each output type entry contains correct `num_rows` matching parquet content
- **AC2.3 Success:** Each output type entry contains correct `num_columns` matching parquet content
- **AC2.4 Success:** Column list contains name and Arrow type for every column in order
- **AC2.5 Edge:** Table with rollup excluded has no rollup entry in manifest

### per-run-manifest.AC3: dpid_map metadata
- **AC3.1 Success:** Manifest includes `dpid_map` entry with `num_surrogates` matching filtered dpid_map row count
- **AC3.2 Edge:** When no masked outputs exist, `num_surrogates` is 0

### per-run-manifest.AC4: Manifest structure
- **AC4.1 Success:** Manifest includes `manifest_version: 1`
- **AC4.2 Success:** Manifest includes correct `agg_type` and `run_id`
- **AC4.3 Success:** File paths in manifest are relative to run directory

### per-run-manifest.AC5: Determinism
- **AC5.1 Success:** Table names are sorted alphabetically
- **AC5.2 Success:** Output type keys are sorted alphabetically
- **AC5.3 Success:** Two runs with identical data produce byte-identical manifests

## Glossary

- **Parquet**: A columnar binary file format used for all aggregated table outputs. Stores data alongside metadata in a file footer, which can be read without scanning the data itself.
- **Arrow type**: The column type system used by Apache Arrow (and exposed by PyArrow). Parquet stores data as Arrow types; these differ from Polars display types and are what downstream consumers see when reading the files.
- **`pyarrow.parquet.read_metadata()`**: A PyArrow function that reads only the footer of a Parquet file, returning row counts and column schema without loading any row data. Available as a transitive dependency through Polars.
- **Atomic write (temp-then-rename)**: Writing output to a temporary file, then using `os.rename()` to move it into place. Because rename is atomic on POSIX filesystems, readers never see a partially-written file.
- **dpid_map**: A CSV artifact produced by the masked output pipeline that maps real participant identifiers to surrogate IDs. The manifest records how many surrogate entries it contains for handoff validation.
- **Determinism**: The property that two runs with identical inputs produce byte-identical output. Required here so manifests can be diffed across runs to detect schema or row-count drift.
- **`manifest_version`**: An integer field in the manifest JSON that allows future schema changes to be detected and handled without breaking existing consumers.

## Architecture

Post-write metadata collection in `writer.py`. After all parquet files and `dpid_map.csv` are written, the run directory is walked to read parquet file metadata. This metadata is assembled into a `manifest.json` and written atomically to the run directory.

The manifest reflects what actually landed on disk, not what the pipeline intended to write. This guarantees the manifest is always truthful -- if a parquet write failed silently, the manifest would not include that file.

**Call order in `write_run()`:**

1. Write parquet files (existing)
2. Write `dpid_map.csv` (existing)
3. Collect parquet metadata, write `manifest.json` (new)
4. Write `run_summary.json` (existing)
5. Update `latest` symlink (existing)

**New functions (both pure):**

- `collect_manifest(run_dir, agg_type, run_id)` -- walks the run directory, reads parquet metadata, returns manifest dict
- `build_manifest_entry(parquet_path, run_dir)` -- reads metadata for a single parquet file, returns per-file dict

Parquet metadata is read via `pyarrow.parquet.read_metadata()`, which reads only the file footer (no data scan). This is a transitive dependency through Polars -- no new dependencies.

**Manifest structure:**

```json
{
  "manifest_version": 1,
  "agg_type": "qa",
  "run_id": "2026-05-21",
  "tables": {
    "ae": {
      "outputs": {
        "stacked": {
          "file": "stacked/ae.parquet",
          "num_rows": 14523,
          "num_columns": 12,
          "columns": [
            {"name": "STUDYID", "type": "large_string"},
            {"name": "AESEQ", "type": "int64"}
          ]
        },
        "masked": {
          "file": "masked/ae.parquet",
          "num_rows": 14523,
          "num_columns": 11,
          "columns": [
            {"name": "STUDYID", "type": "large_string"},
            {"name": "surrogate_id", "type": "large_string"}
          ]
        }
      }
    }
  },
  "dpid_map": {
    "file": "dpid_map.csv",
    "num_surrogates": 342
  }
}
```

**Key structural decisions:**

- `manifest_version: 1` provides a migration path if the schema evolves.
- Column types are Arrow types (what parquet stores), not Polars types. This is what consumers actually see when reading the files.
- File paths are relative to the run directory.
- Table names are sorted alphabetically; output types are sorted alphabetically. This ensures deterministic output for diffing.
- `dpid_map` gets a top-level entry with surrogate count for handoff validation.
- No checksums -- row counts and schema are sufficient for the intended use cases.

## Existing Patterns

Investigation found that all file writes in `writer.py` use the temp-then-rename atomic write pattern. `manifest.json` follows this same pattern.

`run_summary.json` is the existing run-level metadata artifact. It is built by the pure function `build_run_summary()` and written atomically. The manifest follows the same structure: a pure function builds the dict, then it's written via temp-then-rename.

Row counts are already computed and logged during pipeline execution (`pipeline.py:227-235`) but are not persisted. The manifest captures this information from parquet metadata rather than threading it through the pipeline, keeping the two modules decoupled.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Manifest Collection and Writing

**Goal:** Add manifest generation to the run output pipeline.

**Components:**
- `build_manifest_entry()` in `src/pyaggregate/io/writer.py` -- reads parquet metadata for a single file, returns structured dict
- `collect_manifest()` in `src/pyaggregate/io/writer.py` -- walks run directory, calls `build_manifest_entry()` for each parquet file, assembles full manifest dict including `dpid_map` entry
- Integration into `write_run()` -- call `collect_manifest()` after parquet/dpid writes, write `manifest.json` atomically

**Dependencies:** None (first phase).

**Done when:** `manifest.json` is produced in the run directory with correct structure, row counts, column metadata, and dpid_map entry. Tests verify manifest content against known parquet files. Covers `per-run-manifest.AC1.*`, `per-run-manifest.AC2.*`, `per-run-manifest.AC3.*`, `per-run-manifest.AC4.*`.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Determinism and Drift Support

**Goal:** Ensure manifest output is deterministic and suitable for cross-run comparison.

**Components:**
- Key sorting in `collect_manifest()` -- tables alphabetical, output types alphabetical
- JSON serialization with `sort_keys=True` and consistent indent
- Tests verifying deterministic output across multiple writes of the same data

**Dependencies:** Phase 1.

**Done when:** Two runs with identical input produce byte-identical `manifest.json` files. Tests verify key ordering and serialization stability. Covers `per-run-manifest.AC5.*`.
<!-- END_PHASE_2 -->

## Additional Considerations

**Edge case -- empty runs:** If all tables are skipped (exit code 2), `collect_manifest()` still runs but produces a manifest with an empty `tables` object. The manifest is always written regardless of exit code, so consumers can distinguish "run produced nothing" from "run didn't happen."

**Edge case -- rollup exclusion:** Some tables exclude rollup output. The manifest reflects only what was actually written -- if no `rollup/` directory exists for a table, no rollup entry appears in the manifest.
