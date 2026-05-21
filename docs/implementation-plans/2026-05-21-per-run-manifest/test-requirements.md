# Per-Run Manifest -- Test Requirements

**Design:** `docs/design-plans/2026-05-21-per-run-manifest.md`
**Generated:** 2026-05-21

This document maps every acceptance criterion to specific automated tests or documented human verification steps. Each AC must be fully covered before the implementation is considered complete.

---

## Coverage Summary

| AC Group | Total ACs | Automated | Human Verification | Notes |
|----------|-----------|-----------|-------------------|-------|
| AC1: Manifest file produced | 4 | 4 | 0 | Unit + integration |
| AC2: Per-table metadata | 5 | 5 | 0 | Unit |
| AC3: dpid_map metadata | 2 | 2 | 0 | Unit |
| AC4: Manifest structure | 3 | 3 | 0 | Unit |
| AC5: Determinism | 3 | 3 | 0 | Unit + integration |
| AC6: Input provenance | 5 | 5 | 0 | Unit |
| **Total** | **22** | **22** | **0** | |

All acceptance criteria are fully automatable. No human-only verification is required.

---

## AC1: Manifest file produced

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| per-run-manifest.AC1.1 | Integration | `tests/test_writer.py` | `test_write_run_produces_manifest_json` | After a successful `write_run` call (no skipped tables), `manifest.json` exists in the run directory and is valid JSON. |
| per-run-manifest.AC1.2 | Integration | `tests/test_writer.py` | `test_write_run_partial_failure_produces_manifest` | After a `write_run` call with `tables_skipped` (partial failure / exit 2), `manifest.json` still exists in the run directory. |
| per-run-manifest.AC1.3 | Integration | `tests/test_writer.py` | `test_write_run_manifest_atomic_write` | After `write_run` completes, no `manifest.json.tmp` file survives in the run directory. Verifies the temp-then-rename pattern completed. |
| per-run-manifest.AC1.4 | Unit | `tests/test_writer.py` | `test_collect_manifest_empty_run` | Call `collect_manifest` on a run directory with no parquet files; assert `tables` is an empty dict `{}`. |

---

## AC2: Per-table metadata

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| per-run-manifest.AC2.1 | Unit | `tests/test_writer.py` | `test_collect_manifest_lists_output_types` | Each table entry in the manifest lists only the output types that have parquet files on disk (e.g., stacked and masked but not rollup if rollup was excluded). |
| per-run-manifest.AC2.2 | Unit | `tests/test_writer.py` | `test_build_manifest_entry_num_rows` | Write a known DataFrame to parquet via `tmp_path`, call `build_manifest_entry`; assert `num_rows` matches the DataFrame row count. |
| per-run-manifest.AC2.3 | Unit | `tests/test_writer.py` | `test_build_manifest_entry_num_columns` | Write a known DataFrame to parquet via `tmp_path`, call `build_manifest_entry`; assert `num_columns` matches the DataFrame column count. |
| per-run-manifest.AC2.4 | Unit | `tests/test_writer.py` | `test_build_manifest_entry_columns_list` | Write a known DataFrame to parquet, call `build_manifest_entry`; assert `columns` contains every column name and its Arrow type string, in schema order. |
| per-run-manifest.AC2.5 | Unit | `tests/test_writer.py` | `test_collect_manifest_no_rollup_entry` | Create a run directory with stacked and masked parquet files but no rollup directory; call `collect_manifest` and assert the table entry has no `rollup` key in its `outputs`. |

---

## AC3: dpid_map metadata

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| per-run-manifest.AC3.1 | Unit | `tests/test_writer.py` | `test_collect_manifest_dpid_map_count` | Write a `dpid_map.csv` with a known number of rows, call `collect_manifest`; assert `dpid_map.num_surrogates` matches the CSV row count. |
| per-run-manifest.AC3.2 | Unit | `tests/test_writer.py` | `test_collect_manifest_no_masked_zero_surrogates` | Create a run directory with no masked outputs and a header-only `dpid_map.csv` (0 data rows, matching `write_run` behaviour); call `collect_manifest` and assert `num_surrogates` is 0. |

---

## AC4: Manifest structure

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| per-run-manifest.AC4.1 | Unit | `tests/test_writer.py` | `test_collect_manifest_version` | Call `collect_manifest`; assert the returned dict contains `manifest_version: 1`. |
| per-run-manifest.AC4.2 | Unit | `tests/test_writer.py` | `test_collect_manifest_agg_type_and_run_id` | Call `collect_manifest` with known `agg_type` and `run_id`; assert both values appear correctly in the returned dict. |
| per-run-manifest.AC4.3 | Unit | `tests/test_writer.py` | `test_build_manifest_entry_relative_path` | Call `build_manifest_entry` with a parquet file inside a run directory; assert the `file` value is a relative path (no leading `/`, starts with the output type directory name like `stacked/ae.parquet`). |

---

## AC5: Determinism

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| per-run-manifest.AC5.1 | Unit | `tests/test_writer.py` | `test_collect_manifest_table_names_sorted` | Create a run directory with tables in non-alphabetical order (e.g., `dm`, `ae`, `cm`); call `collect_manifest` and assert `list(manifest["tables"].keys())` is in alphabetical order. |
| per-run-manifest.AC5.2 | Unit | `tests/test_writer.py` | `test_collect_manifest_output_types_sorted` | Create a run directory with output types in non-alphabetical order (e.g., `stacked`, `masked`); call `collect_manifest` and assert output type keys within each table are in alphabetical order. |
| per-run-manifest.AC5.3 | Integration | `tests/test_writer.py` | `test_byte_identical_manifests` | Run `write_run` twice with identical inputs into two separate `tmp_path` subdirectories; read both `manifest.json` files as raw strings and assert byte-identical equality. |

---

## AC6: Input provenance

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| per-run-manifest.AC6.1 | Unit | `tests/test_writer.py` | `test_collect_manifest_includes_inputs` | Call `collect_manifest` with a `table_inputs_dict`; assert the returned dict contains a top-level `inputs` key with a dict value keyed by table name. |
| per-run-manifest.AC6.2 | Unit | `tests/test_writer.py` | `test_collect_manifest_input_fields` | Call `collect_manifest` with known `TableInput` objects; assert each entry in the inputs list contains `dpid`, `wpid`, `msoc_path`, and `reqtype` with correct values. |
| per-run-manifest.AC6.3 | Unit | `tests/test_writer.py` | `test_collect_manifest_input_absolute_paths` | Call `collect_manifest` with `TableInput` objects whose `msoc_path` is an absolute `Path`; assert the `msoc_path` value in the manifest starts with `/`. |
| per-run-manifest.AC6.4 | Unit | `tests/test_writer.py` | `test_collect_manifest_inputs_sorted_by_dpid` | Call `collect_manifest` with `TableInput` objects in non-alphabetical dpid order (e.g., `cms` before `aeos`); assert the manifest entries are sorted by dpid. |
| per-run-manifest.AC6.5 | Unit | `tests/test_writer.py` | `test_collect_manifest_skipped_table_no_input` | Call `collect_manifest` with a `table_inputs_dict` that does not include a skipped table; assert the skipped table has no entry in `inputs`. |

---

## Additional Tests (beyond AC coverage)

| Test Name | Test Type | Test File | Verifies |
|-----------|-----------|-----------|----------|
| `test_collect_manifest_inputs_tables_asymmetry` | Unit | `tests/test_writer.py` | A table in `table_inputs_dict` with no corresponding parquet output (failed aggregation) appears in `inputs` but not in `tables`. Intentional: `inputs` reflects what was attempted, `tables` reflects what succeeded. |
| `test_collect_manifest_corrupt_parquet_skipped` | Unit | `tests/test_writer.py` | A corrupt/unreadable parquet file in the run directory is skipped with a warning; the rest of the manifest tables are still collected correctly. |

---

## Human Verification

No acceptance criteria require human verification. All 22 ACs are fully covered by automated tests, plus 2 additional behavioural tests.
