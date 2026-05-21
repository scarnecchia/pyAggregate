# Per-Run Manifest Implementation Plan — Phase 1

**Goal:** Add manifest generation to the run output pipeline so every run produces a `manifest.json` capturing what landed on disk and which source inputs were used.

**Architecture:** Post-write metadata collection in `writer.py`. Two new functions (`build_manifest_entry` and `collect_manifest`) read parquet file footers via `pyarrow.parquet.read_metadata()` and merge input provenance from `TableInput` records, assembling a manifest dict written atomically to the run directory. Minimal CLI change to pass existing `table_inputs_dict` to `write_run()`. No changes to `pipeline.py` or `config.py`.

**Tech Stack:** Python 3.11+, Polars, PyArrow (transitive via Polars), pytest

**Scope:** 2 phases from original design (phases 1-2)

**Codebase verified:** 2026-05-21

---

## Acceptance Criteria Coverage

This phase implements and tests:

### per-run-manifest.AC1: Manifest file produced
- **per-run-manifest.AC1.1 Success:** Every successful run (exit 0) produces `manifest.json` in the run directory
- **per-run-manifest.AC1.2 Success:** Partial failure runs (exit 2) also produce `manifest.json`
- **per-run-manifest.AC1.3 Success:** `manifest.json` is written atomically (temp-then-rename)
- **per-run-manifest.AC1.4 Edge:** Empty run (all tables skipped) produces manifest with empty `tables` object

### per-run-manifest.AC2: Per-table metadata
- **per-run-manifest.AC2.1 Success:** Each table entry lists all output types actually written (stacked, masked, rollup)
- **per-run-manifest.AC2.2 Success:** Each output type entry contains correct `num_rows` matching parquet content
- **per-run-manifest.AC2.3 Success:** Each output type entry contains correct `num_columns` matching parquet content
- **per-run-manifest.AC2.4 Success:** Column list contains name and Arrow type for every column in order
- **per-run-manifest.AC2.5 Edge:** Table with rollup excluded has no rollup entry in manifest

### per-run-manifest.AC3: dpid_map metadata
- **per-run-manifest.AC3.1 Success:** Manifest includes `dpid_map` entry with `num_surrogates` matching filtered dpid_map row count
- **per-run-manifest.AC3.2 Edge:** When no masked outputs exist, `num_surrogates` is 0

### per-run-manifest.AC4: Manifest structure
- **per-run-manifest.AC4.1 Success:** Manifest includes `manifest_version: 1`
- **per-run-manifest.AC4.2 Success:** Manifest includes correct `agg_type` and `run_id`
- **per-run-manifest.AC4.3 Success:** File paths in manifest are relative to run directory

### per-run-manifest.AC6: Input provenance
- **per-run-manifest.AC6.1 Success:** Manifest includes top-level `inputs` object keyed by table name
- **per-run-manifest.AC6.2 Success:** Each table's input list contains all `TableInput` records used (dpid, wpid, msoc_path, reqtype)
- **per-run-manifest.AC6.3 Success:** `msoc_path` values are absolute filesystem paths
- **per-run-manifest.AC6.4 Success:** Input entries within each table are sorted by dpid for determinism
- **per-run-manifest.AC6.5 Edge:** Table with no inputs (skipped) has no entry in `inputs`

### per-run-manifest.AC5: Determinism (structural)
- **per-run-manifest.AC5.1 Success:** Table names are sorted alphabetically
- **per-run-manifest.AC5.2 Success:** Output type keys are sorted alphabetically

---

<!-- START_SUBCOMPONENT_A (tasks 1-4) -->

<!-- START_TASK_1 -->
### Task 1: Implement `build_manifest_entry` helper function

**Verifies:** per-run-manifest.AC2.2, per-run-manifest.AC2.3, per-run-manifest.AC2.4, per-run-manifest.AC4.3

**Files:**
- Modify: `src/pyaggregate/io/writer.py` (add function after `check_run_exists` at line 219)

**Implementation:**

Add a new helper function `build_manifest_entry` that reads a single parquet file's metadata and returns a structured dict. This function performs I/O (reads parquet footer) and belongs in the Imperative Shell (`writer.py`). Add `import pyarrow.parquet as pq` to the imports at the top of the file (after `import polars as pl` on line 11).

```python
import pyarrow.parquet as pq
```

The function:

```python
def build_manifest_entry(parquet_path: Path, run_dir: Path) -> dict:
    """Build manifest entry for a single parquet file from its footer metadata.

    Args:
        parquet_path: Absolute path to the parquet file
        run_dir: Absolute path to the run directory (for computing relative paths)

    Returns:
        Dict with file (relative path), num_rows, num_columns, and columns list
    """
    metadata = pq.read_metadata(str(parquet_path))
    arrow_schema = metadata.schema.to_arrow_schema()

    return {
        "file": str(parquet_path.relative_to(run_dir)),
        "num_rows": metadata.num_rows,
        "num_columns": metadata.num_columns,
        "columns": [
            {"name": field.name, "type": str(field.type)}
            for field in arrow_schema
        ],
    }
```

Key details:
- `pq.read_metadata()` reads only the parquet file footer — no data scan
- `relative_to(run_dir)` produces paths like `stacked/ae.parquet` (AC4.3)
- `arrow_schema` iteration yields `pyarrow.Field` objects with `.name` and `.type`
- Column order matches the parquet schema order (AC2.4)

**Testing:**

Tests must verify each AC listed above:
- per-run-manifest.AC2.2: `num_rows` matches the number of rows in the parquet file
- per-run-manifest.AC2.3: `num_columns` matches the number of columns in the parquet file
- per-run-manifest.AC2.4: `columns` list contains every column name and its Arrow type string, in schema order
- per-run-manifest.AC4.3: `file` value is a relative path (no leading `/`, starts with output type dir)

Test approach: Write a small Polars DataFrame to a parquet file in `tmp_path`, then call `build_manifest_entry` and assert the returned dict matches expected values. Use the existing `table_outputs` fixture pattern from `tests/test_writer.py` as reference.

**Verification:**
Run: `pytest tests/test_writer.py -v -k manifest_entry`
Expected: All tests pass

**Commit:** `feat: add build_manifest_entry helper`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Implement `collect_manifest` helper function

**Verifies:** per-run-manifest.AC1.4, per-run-manifest.AC2.1, per-run-manifest.AC2.5, per-run-manifest.AC3.1, per-run-manifest.AC3.2, per-run-manifest.AC4.1, per-run-manifest.AC4.2, per-run-manifest.AC5.1, per-run-manifest.AC5.2, per-run-manifest.AC6.1, per-run-manifest.AC6.2, per-run-manifest.AC6.3, per-run-manifest.AC6.4, per-run-manifest.AC6.5

**Files:**
- Modify: `src/pyaggregate/io/writer.py` (add function after `build_manifest_entry`)

**Implementation:**

Add `collect_manifest` that walks the run directory, calls `build_manifest_entry` for each parquet file, reads the dpid_map row count, merges input provenance from `table_inputs_dict`, and assembles the full manifest dict. This function performs I/O (directory walk, file reads) and belongs in the Imperative Shell (`writer.py`).

Note: `TableInput` is imported from `pyaggregate.core.input_resolution`. Add this import at the top of `writer.py`:

```python
from pyaggregate.core.input_resolution import TableInput
```

```python
def collect_manifest(
    run_dir: Path,
    agg_type: str,
    run_id: str,
    table_inputs_dict: dict[str, list[TableInput]] | None = None,
) -> dict:
    """Collect manifest metadata from a completed run directory.

    Walks the run directory to read parquet file footers and dpid_map.csv,
    assembling a manifest dict that reflects what actually landed on disk.
    Merges input provenance from resolved TableInput records.

    Args:
        run_dir: Absolute path to the run directory (output_path / run_id)
        agg_type: Aggregation type label (e.g., "qa", "qm", "snapshot")
        run_id: Run identifier
        table_inputs_dict: Resolved inputs per table from resolve_inputs()

    Returns:
        Dict ready for JSON serialization as manifest.json
    """
    if table_inputs_dict is None:
        table_inputs_dict = {}

    tables: dict[str, dict] = {}

    for parquet_file in sorted(run_dir.rglob("*.parquet")):
        try:
            entry = build_manifest_entry(parquet_file, run_dir)
        except Exception:
            logger.warning("Failed to read parquet metadata: %s", parquet_file)
            continue
        output_type = parquet_file.parent.name
        table_name = parquet_file.stem

        if table_name not in tables:
            tables[table_name] = {"outputs": {}}
        tables[table_name]["outputs"][output_type] = entry

    # Sort output type keys within each table for determinism (AC5.2)
    for table_name in tables:
        tables[table_name]["outputs"] = dict(sorted(tables[table_name]["outputs"].items()))

    # Build inputs section from resolved TableInput records (AC6)
    inputs: dict[str, list[dict]] = {}
    for table_name, table_inputs in sorted(table_inputs_dict.items()):
        inputs[table_name] = [
            {
                "dpid": ti.dpid,
                "wpid": ti.wpid,
                "msoc_path": str(ti.msoc_path),
                "reqtype": ti.reqtype,
            }
            for ti in sorted(table_inputs, key=lambda ti: ti.dpid)
        ]

    # Read dpid_map surrogate count from disk (intentional: manifest reflects
    # what actually landed on disk, not what the pipeline intended to write)
    dpid_map_path = run_dir / "dpid_map.csv"
    num_surrogates = 0
    if dpid_map_path.exists():
        dpid_df = pl.read_csv(dpid_map_path)
        num_surrogates = len(dpid_df)

    return {
        "manifest_version": 1,
        "agg_type": agg_type,
        "run_id": run_id,
        "tables": dict(sorted(tables.items())),
        "inputs": inputs,
        "dpid_map": {
            "file": "dpid_map.csv",
            "num_surrogates": num_surrogates,
        },
    }
```

Key details:
- `sorted(run_dir.rglob("*.parquet"))` ensures deterministic file discovery order
- Table names extracted from `parquet_file.stem`, output types from `parquet_file.parent.name`
- `dict(sorted(tables.items()))` sorts tables alphabetically (AC5.1)
- Output type keys sorted alphabetically within each table (AC5.2)
- Corrupt/unreadable parquet files are logged and skipped, matching the error-tolerance pattern in `write_run`
- dpid_map row count read from disk via `pl.read_csv` — this is an intentional design choice: the manifest reflects what actually landed on disk ("truthful by construction"), not what the pipeline intended to write
- When no masked outputs exist, `dpid_map.csv` has 0 rows → `num_surrogates` is 0 (AC3.2)
- Empty run (no parquet files) → `tables` dict is empty (AC1.4)
- `inputs` keyed by table name, each entry is a list of dicts with dpid, wpid, msoc_path, reqtype (AC6.1, AC6.2)
- `msoc_path` converted to string via `str(ti.msoc_path)` — preserves absolute paths (AC6.3)
- Input entries sorted by dpid within each table (AC6.4)
- `table_inputs_dict` iteration uses `sorted()` for table name ordering; tables with no inputs (skipped) are not included if they're not in `table_inputs_dict` (AC6.5)
- `table_inputs_dict` defaults to `None` (empty dict) for backward compatibility with direct `collect_manifest` calls in tests

**Testing:**

Tests must verify each AC listed above:
- per-run-manifest.AC1.4: Call after a run with no table outputs → `tables` is empty dict
- per-run-manifest.AC2.1: Each table entry lists only the output types that have parquet files on disk
- per-run-manifest.AC2.5: Table without rollup parquet file has no `rollup` key in its `outputs`
- per-run-manifest.AC3.1: `dpid_map.num_surrogates` matches the number of rows in the CSV on disk
- per-run-manifest.AC3.2: When no masked outputs exist, `dpid_map.csv` is a header-only CSV (0 data rows) and `num_surrogates` is 0
- per-run-manifest.AC4.1: `manifest_version` is 1
- per-run-manifest.AC4.2: `agg_type` and `run_id` match the values passed in
- per-run-manifest.AC5.1: Table names appear in alphabetical order in the manifest dict
- per-run-manifest.AC5.2: Output type keys appear in alphabetical order within each table
- per-run-manifest.AC6.1: Manifest contains top-level `inputs` key with dict value keyed by table name
- per-run-manifest.AC6.2: Each table's input list contains dicts with all four TableInput fields
- per-run-manifest.AC6.3: `msoc_path` values are absolute paths (start with `/`)
- per-run-manifest.AC6.4: Input entries within each table are sorted by dpid
- per-run-manifest.AC6.5: Table not in `table_inputs_dict` has no entry in `inputs`
- **Additional: inputs/tables asymmetry**: A table in `table_inputs_dict` that has no parquet output (failed aggregation) still appears in `inputs` but not in `tables`. This is intentional — `inputs` reflects what was attempted, `tables` reflects what succeeded.
- **Additional: corrupt parquet tolerance**: A corrupt parquet file in the run directory is skipped with a warning; the rest of the manifest is still correct.

Test approach: Use `write_run` to create a real run directory in `tmp_path` (reusing the existing `table_outputs` and `dpid_map` fixtures), construct a `table_inputs_dict` with `TableInput` objects, then call `collect_manifest` on the result and assert the returned dict. For edge cases (empty run, no masked), create minimal table_outputs dicts. For key ordering tests, use table_outputs with deliberately unordered keys. For input provenance tests, create TableInput objects with known values and verify they appear in the manifest.

**Verification:**
Run: `pytest tests/test_writer.py -v -k collect_manifest`
Expected: All tests pass

**Commit:** `feat: add collect_manifest helper`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Integrate manifest writing into `write_run`

**Verifies:** per-run-manifest.AC1.1, per-run-manifest.AC1.2, per-run-manifest.AC1.3

**Files:**
- Modify: `src/pyaggregate/io/writer.py:16-24` (add `table_inputs_dict` parameter to `write_run` signature)
- Modify: `src/pyaggregate/io/writer.py:97-121` (add manifest write between dpid_map and run_summary)

**Implementation:**

**1. Add `table_inputs_dict` parameter to `write_run` signature.**

Add a new optional parameter to `write_run()` after `tables_skipped`:

```python
def write_run(
    output_path: Path,
    agg_type: str,
    run_id: str,
    table_outputs: dict[str, dict[str, pl.DataFrame]],
    dpid_map_frame: pl.DataFrame,
    update_latest: bool,
    tables_skipped: list[dict] | None = None,
    table_inputs_dict: dict[str, list[TableInput]] | None = None,
) -> None:
```

The parameter is optional with `None` default for backward compatibility with existing tests that don't pass input provenance.

**2. Insert manifest collection and atomic write.**

Add between the dpid_map write (line 101) and the run_summary build (line 103). The manifest must be written after dpid_map.csv (it reads the CSV) and before run_summary.json (per the design's call order):

```python
    # Collect and write manifest.json from post-write inspection
    manifest = collect_manifest(run_dir, agg_type, run_id, table_inputs_dict)
    manifest_path = run_dir / "manifest.json"
    manifest_tmp = run_dir / "manifest.json.tmp"
    with open(manifest_tmp, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    os.rename(str(manifest_tmp), str(manifest_path))
```

This follows the exact same atomic write pattern used for `run_summary.json` (lines 117-121) and `dpid_map.csv` (lines 98-101).

Also update the test imports. The existing `write_run` import in `tests/test_writer.py` line 9 should also import the new functions:

```python
from pyaggregate.io.writer import (
    build_manifest_entry,
    check_run_exists,
    collect_manifest,
    filter_dpid_map,
    write_run,
)
```

And import `TableInput` for tests that pass input provenance:

```python
from pyaggregate.core.input_resolution import TableInput
```

**Testing:**

Tests must verify each AC listed above:
- per-run-manifest.AC1.1: After a successful `write_run` call (no skipped tables), `manifest.json` exists in the run directory
- per-run-manifest.AC1.2: After a `write_run` call with `tables_skipped` (partial failure), `manifest.json` still exists
- per-run-manifest.AC1.3: No `manifest.json.tmp` file survives after write (atomic write verified)

Test approach: Call `write_run` with the existing fixtures, then check `manifest.json` exists and can be parsed as valid JSON. For AC1.2, pass `tables_skipped` parameter. For AC1.3, verify no `.tmp` files remain (the existing `test_write_run_no_tmp_files_survive` pattern covers this implicitly, but add an explicit manifest.json.tmp check). Existing tests that don't pass `table_inputs_dict` should continue to work unchanged (default `None`).

**Verification:**
Run: `pytest tests/test_writer.py -v`
Expected: All tests pass (existing + new)

**Commit:** `feat: write manifest.json in write_run after dpid_map`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Pass `table_inputs_dict` from CLI to `write_run`

**Verifies:** per-run-manifest.AC6.1, per-run-manifest.AC6.2, per-run-manifest.AC6.3

**Files:**
- Modify: `src/pyaggregate/cli.py:233-241` (add `table_inputs_dict` to `write_run` call)

**Implementation:**

In the CLI's `run` command, `table_inputs_dict` is already available from `resolve_inputs()` at line 192. Pass it to `write_run()` at lines 233-241:

```python
    write_run(
        output_path=agg_config.output_path,
        agg_type=agg_type,
        run_id=run_id,
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map_df,
        update_latest=update_latest,
        tables_skipped=tables_skipped,
        table_inputs_dict=table_inputs_dict,
    )
```

This is a one-line addition to the existing call. The `table_inputs_dict` variable is already in scope from `resolve_inputs()` on line 192.

**Testing:**

This is an integration point — the CLI passes data through to the writer. The existing AC6 tests on `collect_manifest` verify the data structure is correct. This task ensures the CLI wiring is in place. Full end-to-end verification happens via the existing e2e smoke test pattern if applicable, or by running the CLI and inspecting the manifest.

**Verification:**
Run: `pytest tests/ -v`
Expected: All tests pass (no regressions)

**Commit:** `feat: pass input provenance from CLI to manifest`
<!-- END_TASK_4 -->

<!-- END_SUBCOMPONENT_A -->
