# Rework Output Config — Test Requirements

**Design:** `docs/design-plans/2026-05-20-rework-output-config.md`
**Generated:** 2026-05-20

This document maps every acceptance criterion to specific automated tests or documented human verification steps. Each AC must be fully covered before the implementation is considered complete.

---

## Coverage Summary

| AC Group | Total ACs | Automated | Human Verification | Notes |
|----------|-----------|-----------|-------------------|-------|
| AC1: Per-agg output_path | 5 | 5 | 0 | Unit + integration |
| AC2: Writer signature | 4 | 4 | 0 | Unit |
| AC3: Latest symlink | 3 | 3 | 0 | Unit |
| AC4: Legacy schema rejection | 3 | 3 | 0 | Unit + CLI |
| AC5: sdd to snapshot rename | 3 | 3 | 0 | Unit + integration |
| AC6: Cross-cutting | 2 | 2 | 0 | Suite-level + load test |
| **Total** | **20** | **20** | **0** | |

All acceptance criteria are fully automatable. No human-only verification is required.

---

## AC1: Per-agg output_path is honoured

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| AC1.1 | Unit | `tests/test_config.py` | `test_load_valid_config` | Config loads per-agg `output_path` into `AggTypeConfig`; assert `config.agg_types["qa"].output_path == Path("/data/outputs/qa")` and same for snapshot. |
| AC1.1 | Integration | `tests/test_e2e_smoke.py` | `test_full_pipeline_ac9_1` | TOML fixture declares per-agg `output_path` values; after pipeline run, `_verify_output_files_exist` confirms parquet files at `{output_path}/{run_id}/{stacked,masked,rollup}/<table>.parquet`. |
| AC1.2 | Integration | `tests/test_e2e_smoke.py` | `test_full_pipeline_ac9_1` | Explicit assertion after pipeline run that all three agg output paths are distinct directories under `output_dir` — no shared parent in the path layout beyond the test root. |
| AC1.2 | Integration | `tests/test_run_orchestration.py` | `test_run_with_type_filter_qa_snapshot_only` | Runs `--type qa --type snapshot`; verifies each agg's outputs land under its own `config.agg_types[t].output_path`, not a shared root. |
| AC1.3 | Unit | `tests/test_config.py` | `test_output_path_tilde_expansion` | TOML fixture with `output_path = "~/outputs/qa"`; assert `config.agg_types["qa"].output_path == Path.home() / "outputs" / "qa"`. Confirms `expanduser()` at load time. |
| AC1.4 | Unit | `tests/test_config.py` | `test_missing_output_path_rejected` | TOML fixture with `[agg.qa]` missing `output_path`; assert `pytest.raises(ValueError, match="\\[agg\\.qa\\].*output_path")`. |
| AC1.5 | Unit | `tests/test_config.py` | `test_output_path_relative_preserved` | TOML fixture with `output_path = "relative/path"`; assert `config.agg_types["qa"].output_path == Path("relative/path")` — not absolutized by `resolve()`. |

### Implementation rationale

- AC1.1 is tested at two levels: unit (config correctly parses the field) and integration (pipeline actually writes to the path). The unit test is in Phase 1; the integration test is in Phase 4.
- AC1.2 requires a multi-agg invocation, which only the orchestration and E2E tests exercise. The E2E test adds an explicit parent-path assertion to catch regressions where agg types accidentally share path segments.
- AC1.3, AC1.4, and AC1.5 are pure config-load behaviours — unit tests in `test_config.py` are sufficient. No integration coverage needed since path expansion happens once at load time and the expanded `Path` object is what flows downstream.

---

## AC2: Writer signature and path composition

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| AC2.1 | Unit | `tests/test_writer.py` | `test_write_run_creates_directory_structure` | After `write_run(output_path=..., ...)`, asserts `dpid_map.csv` and `run_summary.json` exist at `{output_path}/{run_id}/` (no `agg_type` segment in path). |
| AC2.1 | Unit | `tests/test_writer.py` | `test_write_run_dpid_map_filtered` | Asserts `dpid_map.csv` written at `{output_path}/{run_id}/dpid_map.csv` with correct content. |
| AC2.1 | Integration | `tests/test_e2e_smoke.py` | `test_full_pipeline_ac9_1` | `_verify_dpid_map_valid` helper confirms `dpid_map.csv` at `{output_path}/{run_id}/` for each agg type. |
| AC2.2 | Unit | `tests/test_writer.py` | `test_write_run_summary_json` | Reads `run_summary.json` at `{output_path}/{run_id}/`; asserts it contains both `agg_type` and `run_id` fields even though `agg_type` is absent from the path. |
| AC2.3 | Unit | `tests/test_writer.py` | `test_check_run_exists_returns_true` | Creates `{output_path}/{run_id}/` directory; calls `check_run_exists(output_path, run_id)` (2-arg signature); asserts `True`. |
| AC2.3 | Unit | `tests/test_writer.py` | `test_check_run_exists_returns_false` | Calls `check_run_exists(output_path, run_id)` without creating the directory; asserts `False`. |
| AC2.4 | Unit | `tests/test_run_orchestration.py` | `test_run_partial_failure_exit_code_2` | Simulates per-table write failure; asserts failed tables in `tables_skipped` and exit code 2. Confirms path refactor does not change failure semantics. |
| AC2.4 | Unit | `tests/test_run_orchestration.py` | `test_run_full_failure_exit_code_1` | Simulates complete write failure; asserts exit code 1. Confirms failure semantics unchanged by path refactor. |

### Implementation rationale

- AC2.1 and AC2.2 are writer-level behaviours tested directly in `test_writer.py`. The E2E layer provides redundant integration coverage via the `_verify_dpid_map_valid` helper.
- AC2.3 tests the simplified 2-arg signature of `check_run_exists`. Both the positive and negative cases are existing tests updated for the new signature.
- AC2.4 does not introduce new tests — the existing failure-semantics tests are retained unmodified (only path shapes change in their fixtures). The implementation plan explicitly states "the path refactor does not change failure semantics," so verifying the existing tests still pass is the correct coverage.

---

## AC3: Latest symlink

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| AC3.1 | Unit | `tests/test_writer.py` | `test_write_run_latest_symlink_created` | After `write_run(output_path=..., update_latest=True)`, asserts symlink exists at `{output_path}/latest` and resolves to `{run_id}`. |
| AC3.1 | Integration | `tests/test_e2e_smoke.py` | `test_full_pipeline_ac9_1` | `_verify_latest_symlinks` helper confirms `{output_path}/latest` exists and is a symlink for each agg type. |
| AC3.2 | Unit | `tests/test_writer.py` | `test_write_run_atomic_symlink_update` | Calls `write_run` twice with different `run_id` values; asserts `latest` symlink target changes and no intermediate state is observable (temp-then-rename pattern). |
| AC3.3 | Integration | `tests/test_run_orchestration.py` | `test_run_with_type_filter_qa_snapshot_only` | Runs `--type qa --type snapshot`; asserts `{qa.output_path}/latest` and `{snapshot.output_path}/latest` each point to the correct `run_id`. Asserts running one agg does not touch the other's symlink. |
| AC3.3 | Integration | `tests/test_run_orchestration.py` | `test_run_updates_latest_symlink_on_success` | Runs a single agg type; verifies only that agg's `{output_path}/latest` is created/updated. |

### Implementation rationale

- AC3.1 and AC3.2 are direct writer behaviours, testable at the unit level.
- AC3.3 (independence) requires multi-agg orchestration — the orchestration test is the natural home. The test must verify that running `--type qa` does NOT create or update `{snapshot.output_path}/latest`.
- Atomicity (AC3.2) is tested by the existing `test_write_run_atomic_symlink_update` test, which calls `write_run` twice and verifies the symlink is always valid. True concurrency testing of the temp-then-rename pattern is not attempted — the pattern is a well-understood OS-level guarantee when source and destination are on the same filesystem.

---

## AC4: Legacy schema rejection

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| AC4.1 | Unit | `tests/test_config.py` | `test_legacy_output_section_rejected` | TOML fixture with `[output]\noutput_root = "/data/outputs"` alongside valid `[scan]` and `[state]`. Asserts `pytest.raises(ValueError, match="\\[output\\] section has been removed")`. Verifies error message references the new per-agg `output_path` field with a concrete example. |
| AC4.2 | Unit | `tests/test_config.py` | `test_legacy_output_section_rejected` | Same test covers AC4.2 — the TOML fixture includes `output_root` inside `[output]`, triggering the same rejection guard. The guard fires on the presence of the `[output]` key in TOML data, regardless of its contents. |
| AC4.3 | Unit | `tests/test_run_orchestration.py` | `test_run_output_root_flag_rejected_ac4_3` | Invokes CLI with `--output-root /some/path`; asserts non-zero exit code. Typer rejects unrecognised options before the command body runs. |

### Implementation rationale

- AC4.1 and AC4.2 are both covered by a single test because the rejection guard fires on the `"output" in data` check. The implementation plan specifies that `output_root` inside any `[output]`-like section triggers the same migration message — this is structurally guaranteed by the guard checking at the section level.
- AC4.3 is a CLI-level test. The implementation plan replaces the deleted `test_run_with_alternate_output_root` tests with this explicit rejection test. Typer's built-in option validation handles the rejection; the test confirms the user-facing behaviour.

---

## AC5: sdd to snapshot rename

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| AC5.1 | Integration | `tests/test_run_orchestration.py` | `test_run_with_type_filter_qa_snapshot_only` | CLI invocation with `--type snapshot` selects the snapshot agg type; pipeline runs and produces outputs under `config.agg_types["snapshot"].output_path`. |
| AC5.1 | Integration | `tests/test_e2e_smoke.py` | `test_full_pipeline_ac9_1` | TOML fixture uses `[agg.snapshot]`; full pipeline run succeeds with `--type snapshot` in the agg type list. |
| AC5.2 | Unit | `tests/test_run_orchestration.py` | (existing) `test_run_unknown_type` | Config declares `[agg.snapshot]` (no `[agg.sdd]`). CLI invocation with `--type sdd` exits non-zero. The error message lists configured types (which now include `snapshot` but not `sdd`). |
| AC5.3 | Unit | `tests/test_input_resolution.py` | `test_filter_catalog_snapshot_config_filters_has_scdm` | Calls `detect_snapshot_collisions()` (renamed from `detect_sdd_collisions`); verifies collision-detection behaviour is unchanged. |
| AC5.3 | Unit | `tests/test_input_resolution.py` | (multiple collision tests) | All tests that previously called `detect_sdd_collisions(...)` now call `detect_snapshot_collisions(...)` — function import and behaviour verified. |

### Implementation rationale

- AC5.1 does not require a new test — renaming the fixture from `[agg.sdd]` to `[agg.snapshot]` and the CLI args from `--type sdd` to `--type snapshot` in existing tests is the verification. If the rename is incomplete, these tests fail.
- AC5.2 is verified by the existing `test_run_unknown_type` test after the rename. Once the config only declares `[agg.snapshot]`, passing `--type sdd` triggers the "unknown agg type" error path. No new test needed — the existing test implicitly covers this. If an explicit test is desired for traceability, a dedicated `test_sdd_rejected_after_rename` test can be added, but the implementation plan does not call for one.
- AC5.3 is verified by the import change in `test_input_resolution.py`. If `detect_snapshot_collisions` is not importable, every test in that file that references it fails at collection time.

---

## AC6: Cross-cutting

| AC ID | Test Type | Test File | Test Name | Verifies |
|-------|-----------|-----------|-----------|----------|
| AC6.1 | Suite | (all test files) | Full `pytest` suite | All tests pass. Additionally, Phase 4 Task 3 runs four `grep` sweeps to assert zero matches for `OutputConfig`, `output_root` (as config field), `--output-root`, and `sdd` (as agg identifier) across `src/` and `tests/`. |
| AC6.2 | Unit | (Phase 4 Task 2 verification) | `load_config(Path('pyaggregate.toml'))` | The root example config `pyaggregate.toml` is loadable by `load_config()` without modification. Returns 3 agg types: `['qa', 'qm', 'snapshot']`. |

### Implementation rationale

- AC6.1 is a meta-criterion — it is satisfied when the full test suite passes and no dead references remain. The implementation plan defines explicit `grep` commands in Phase 4 Task 3 as automated verification. These could be elevated to a dedicated test (e.g., a test that shells out to `grep` or uses `ast` to scan imports), but the plan treats them as CI-level verification steps rather than pytest tests. The full suite pass is the primary gate.
- AC6.2 is verified by loading the example config file. The implementation plan runs this as a one-off command in Phase 4 Task 2. To make this a persistent automated test, a test could be added to `test_config.py` that loads `pyaggregate.toml` from the repo root and asserts the expected agg types. The implementation plan does not explicitly create this test, but the verification command serves the same purpose during implementation.

---

## Test File Change Summary

This table summarises which test files are modified or created in each phase, and which ACs they contribute to.

| Test File | Phase | Changes | ACs Covered |
|-----------|-------|---------|-------------|
| `tests/test_config.py` | 1, 3 | Update fixtures (remove `[output]`, add per-agg `output_path`); add 4 new tests; rename `sdd` to `snapshot` in fixtures | AC1.1, AC1.3, AC1.4, AC1.5, AC4.1, AC4.2 |
| `tests/test_writer.py` | 2 | Update all 17 tests: `output_root` kwarg to `output_path`, remove `agg_type` path segment, update `check_run_exists` to 2-arg signature | AC2.1, AC2.2, AC2.3, AC3.1, AC3.2 |
| `tests/test_run_orchestration.py` | 2, 3 | Remove `OutputConfig` import; update fixture to per-agg `output_path`; delete 2 `--output-root` tests; add AC4.3 rejection test; rename `sdd` to `snapshot`; update all path assertions | AC2.4, AC3.1, AC3.3, AC4.3, AC5.1, AC5.2 |
| `tests/test_input_resolution.py` | 3 | Rename `detect_sdd_collisions` to `detect_snapshot_collisions` in imports and calls; rename test functions | AC5.3 |
| `tests/test_e2e_smoke.py` | 3, 4 | Rename `sdd` to `snapshot` in TOML fixtures and loops; update helper signatures to `dict[str, Path]`; add AC1.2 explicit assertion | AC1.1, AC1.2, AC2.1, AC3.1, AC5.1 |
| `tests/test_scanner.py` | 2 | Remove `OutputConfig` from fixture; no new ACs (fixture maintenance) | — |
| `tests/test_scanner_concurrency.py` | 2 | Remove `OutputConfig` from fixture; no new ACs (fixture maintenance) | — |

---

## New Tests Created

These are tests that do not exist in the current codebase and must be written as part of this implementation.

| Test Name | File | Phase | ACs |
|-----------|------|-------|-----|
| `test_legacy_output_section_rejected` | `tests/test_config.py` | 1 | AC4.1, AC4.2 |
| `test_missing_output_path_rejected` | `tests/test_config.py` | 1 | AC1.4 |
| `test_output_path_tilde_expansion` | `tests/test_config.py` | 1 | AC1.3 |
| `test_output_path_relative_preserved` | `tests/test_config.py` | 1 | AC1.5 |
| `test_run_output_root_flag_rejected_ac4_3` | `tests/test_run_orchestration.py` | 2 | AC4.3 |

---

## Deleted Tests

These tests are removed because the functionality they tested no longer exists.

| Test Name | File | Phase | Reason |
|-----------|------|-------|--------|
| `test_run_with_alternate_output_root` | `tests/test_run_orchestration.py` | 2 | `--output-root` CLI flag removed. Replaced by `test_run_output_root_flag_rejected_ac4_3`. |
| `test_run_with_alternate_output_root_ac4_2` | `tests/test_run_orchestration.py` | 2 | Same — `--output-root` CLI flag removed. |

---

## Traceability Matrix

Every AC mapped to its primary test(s). "Primary" means the test whose failure would directly indicate the AC is broken.

| AC | Primary Test | File | Type |
|----|-------------|------|------|
| AC1.1 | `test_load_valid_config` | `tests/test_config.py` | Unit |
| AC1.1 | `test_full_pipeline_ac9_1` | `tests/test_e2e_smoke.py` | Integration |
| AC1.2 | `test_full_pipeline_ac9_1` (explicit parent assertion) | `tests/test_e2e_smoke.py` | Integration |
| AC1.2 | `test_run_with_type_filter_qa_snapshot_only` | `tests/test_run_orchestration.py` | Integration |
| AC1.3 | `test_output_path_tilde_expansion` | `tests/test_config.py` | Unit |
| AC1.4 | `test_missing_output_path_rejected` | `tests/test_config.py` | Unit |
| AC1.5 | `test_output_path_relative_preserved` | `tests/test_config.py` | Unit |
| AC2.1 | `test_write_run_creates_directory_structure` | `tests/test_writer.py` | Unit |
| AC2.2 | `test_write_run_summary_json` | `tests/test_writer.py` | Unit |
| AC2.3 | `test_check_run_exists_returns_true` | `tests/test_writer.py` | Unit |
| AC2.4 | `test_run_partial_failure_exit_code_2` | `tests/test_run_orchestration.py` | Unit |
| AC3.1 | `test_write_run_latest_symlink_created` | `tests/test_writer.py` | Unit |
| AC3.2 | `test_write_run_atomic_symlink_update` | `tests/test_writer.py` | Unit |
| AC3.3 | `test_run_with_type_filter_qa_snapshot_only` | `tests/test_run_orchestration.py` | Integration |
| AC4.1 | `test_legacy_output_section_rejected` | `tests/test_config.py` | Unit |
| AC4.2 | `test_legacy_output_section_rejected` | `tests/test_config.py` | Unit |
| AC4.3 | `test_run_output_root_flag_rejected_ac4_3` | `tests/test_run_orchestration.py` | Unit |
| AC5.1 | `test_run_with_type_filter_qa_snapshot_only` | `tests/test_run_orchestration.py` | Integration |
| AC5.2 | `test_run_unknown_type` | `tests/test_run_orchestration.py` | Unit |
| AC5.3 | `test_filter_catalog_snapshot_config_filters_has_scdm` | `tests/test_input_resolution.py` | Unit |
| AC6.1 | Full `pytest` suite + dead reference `grep` sweep | (all files) | Suite |
| AC6.2 | `load_config(Path('pyaggregate.toml'))` verification | (Phase 4 Task 2) | Verification |
