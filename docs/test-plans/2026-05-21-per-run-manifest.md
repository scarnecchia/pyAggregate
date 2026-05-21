# Human Test Plan: Per-Run Manifest

## Prerequisites
- Python 3.11+ environment with pyaggregate installed (`pip install -e .`)
- `pytest` passing: `pytest tests/test_writer.py -v` (all 22+ tests green)
- Access to a test data directory with at least one SAS7BDAT file

## Phase 1: Manifest File Creation

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Run `pyaggregate run --config pyaggregate.example.toml` with valid scan results | Run completes; `manifest.json` exists in the run output directory alongside parquet files |
| 1.2 | Open `manifest.json` in a JSON viewer/formatter | Valid JSON; no trailing commas, no syntax errors |
| 1.3 | Kill the process mid-run (Ctrl+C during aggregation), check output directory | No `manifest.json.tmp` file remains; if manifest.json exists it is valid JSON (not partial) |

## Phase 2: Manifest Content Accuracy

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Open `manifest.json`, check `manifest_version` | Value is exactly `1` (integer, not string) |
| 2.2 | Compare `agg_type` and `run_id` in manifest to the CLI invocation | Match exactly (e.g., `"qa"` and `"2026-05-21"`) |
| 2.3 | For any table listed in `tables`, count rows in the corresponding parquet file using `polars.scan_parquet(...).collect().height` | Matches `num_rows` in manifest |
| 2.4 | For any table, list columns in parquet with `polars.read_parquet_schema(...)` | Column names and types match `columns` array in manifest |
| 2.5 | Check `dpid_map.num_surrogates` against `wc -l dpid_map.csv` minus header | Values match |

## Phase 3: Determinism Verification

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | Run the same aggregation twice with identical inputs into two different output paths | Both `manifest.json` files are byte-identical (`diff` or `shasum` both) |
| 3.2 | Inspect `tables` keys in manifest.json | Alphabetical order |
| 3.3 | Inspect output type keys within any table entry | Alphabetical order (e.g., `masked` before `stacked`) |

## Phase 4: Input Provenance

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | Run with `--table-inputs` or equivalent config providing input metadata | `inputs` key present in manifest with entries keyed by table name |
| 4.2 | Verify an input entry contains `dpid`, `wpid`, `msoc_path`, `reqtype` | All four fields present with non-null values |
| 4.3 | Verify `msoc_path` values are absolute paths | Each starts with `/` |
| 4.4 | Verify input entries within a table are sorted by dpid | Alphabetical ordering confirmed |

## End-to-End: Full Pipeline with Partial Failure

**Purpose:** Validates manifest correctness when some tables fail aggregation (exit code 2 scenario).

| Step | Action | Expected |
|------|--------|----------|
| E2E.1 | Configure a run where one table's input is corrupted/missing | Run completes with exit code 2 |
| E2E.2 | Check `manifest.json` exists | Present in run directory |
| E2E.3 | Verify successful tables appear in `manifest.tables` | Only successfully written tables listed |
| E2E.4 | Verify failed table does NOT appear in `manifest.tables` | Absent from tables dict |
| E2E.5 | Check `run_summary.json` for `tables_skipped` | Failed table listed with error_class and detail |

## End-to-End: Empty Run

**Purpose:** Validates manifest handles the edge case where all tables are skipped.

| Step | Action | Expected |
|------|--------|----------|
| E2E.6 | Configure a run where all inputs are invalid | Run produces manifest.json |
| E2E.7 | Open manifest.json | `tables` is `{}`, `dpid_map.num_surrogates` is 0 |

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| AC1.1 | `test_manifest_json_created_after_successful_run` | 1.1, 1.2 |
| AC1.2 | `test_manifest_json_created_with_skipped_tables` | E2E.2 |
| AC1.3 | `test_manifest_json_atomic_write` | 1.3 |
| AC1.4 | `test_manifest_empty_run` | E2E.7 |
| AC2.1 | `test_manifest_lists_output_types_present` | 2.3 |
| AC2.2 | `test_manifest_entry_num_rows` | 2.3 |
| AC2.3 | `test_manifest_entry_num_columns` | 2.4 |
| AC2.4 | `test_manifest_entry_columns_list` | 2.4 |
| AC2.5 | `test_manifest_table_without_rollup` | 2.3 |
| AC3.1 | `test_manifest_dpid_map_num_surrogates` | 2.5 |
| AC3.2 | `test_manifest_no_masked_outputs_zero_surrogates` | E2E.7 |
| AC4.1 | `test_manifest_version_and_agg_type` | 2.1 |
| AC4.2 | `test_manifest_version_and_agg_type` | 2.2 |
| AC4.3 | `test_manifest_entry_relative_path` | 2.3 |
| AC5.1 | `test_manifest_tables_sorted_alphabetically` | 3.2 |
| AC5.2 | `test_manifest_output_types_sorted_alphabetically` | 3.3 |
| AC5.3 | `test_byte_identical_manifests_from_identical_inputs` | 3.1 |
| AC6.1 | `test_manifest_input_provenance_structure` | 4.1 |
| AC6.2 | `test_manifest_input_provenance_structure` | 4.2 |
| AC6.3 | `test_manifest_msoc_path_absolute` | 4.3 |
| AC6.4 | `test_manifest_inputs_sorted_by_dpid` | 4.4 |
| AC6.5 | `test_manifest_table_with_no_inputs` | E2E.4 |
