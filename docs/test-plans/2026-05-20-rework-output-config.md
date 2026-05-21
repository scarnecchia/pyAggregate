# Human Test Plan: Rework Output Config

**Feature:** Per-agg output_path, sdd→snapshot rename, legacy schema rejection
**Generated:** 2026-05-20
**Automated coverage:** 202 tests (20/20 ACs covered)

## Prerequisites

- Python 3.11+ with `uv` available
- `uv run pytest tests/ -v` passes (202 passed, 1 skipped)
- Access to a machine where you can create files, directories, and symlinks (Linux/macOS)

## Phase 1: Config Loading and Validation

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Open `pyaggregate.example.toml` in the repo root. Inspect that each `[agg.*]` block has an `output_path` field and no `[output]` section exists. | Three agg blocks (`qa`, `qm`, `snapshot`), each with `output_path`. No `[output]` section. |
| 1.2 | Create a TOML file with a `[output]` section containing `output_root = "/tmp/test"` alongside valid `[scan]` and `[state]`. Run `uv run python -c "from pyaggregate.config import load_config; from pathlib import Path; load_config(Path('your_file.toml'))"`. | `ValueError` raised with message containing "[output] section has been removed". |
| 1.3 | Create a TOML file with `[agg.qa]` that has `source_reqtype = "qar"` but no `output_path`. Attempt to load it. | `ValueError` raised with message matching `[agg.qa]` and `output_path`. |
| 1.4 | Create a TOML file with `output_path = "~/my/outputs"` in an agg block. Load it and inspect the result. | `output_path` resolves to `/home/<user>/my/outputs` (home directory expanded). |
| 1.5 | Create a TOML file with `output_path = "relative/path"`. Load it and inspect. | `output_path` is `Path("relative/path")` -- not absolutized by `resolve()`. |

## Phase 2: Writer Path Composition

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Run the full pipeline with a valid config (`uv run pyaggregate run --config <config> --type qa --run-id test-manual`). Navigate to the qa `output_path`. | Directory structure is `{output_path}/test-manual/stacked/`, `{output_path}/test-manual/masked/`, `{output_path}/test-manual/rollup/`. No `qa/` segment between `output_path` and `run_id`. |
| 2.2 | In the same run output, open `test-manual/run_summary.json`. | JSON contains both `"agg_type": "qa"` and `"run_id": "test-manual"` fields. |
| 2.3 | In the same run output, check for `test-manual/dpid_map.csv`. | File exists at `{output_path}/test-manual/dpid_map.csv` with `surrogate_id` and `dpid` columns. |

## Phase 3: Latest Symlink Behaviour

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | After a successful run (step 2.1), check `{output_path}/latest`. | `latest` is a symlink pointing to `test-manual`. `ls -la` shows `latest -> test-manual`. |
| 3.2 | Run again with `--run-id test-manual-2`. Check `{output_path}/latest` again. | Symlink now points to `test-manual-2`. The previous `test-manual` directory still exists. |
| 3.3 | Run with `--no-update-latest --run-id test-manual-3`. Check `{output_path}/latest`. | Symlink still points to `test-manual-2` (unchanged). `test-manual-3` directory exists. |
| 3.4 | Run `--type qa` and `--type snapshot` together. Check both `{qa_output_path}/latest` and `{snapshot_output_path}/latest`. Verify `{qm_output_path}/latest` does not exist (if qm was never run). | Each agg type has its own independent `latest` symlink. Running one agg does not create or modify another's symlink. |

## Phase 4: Legacy Rejection

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | Run `uv run pyaggregate run --output-root /tmp/test --config <valid_config>`. | Non-zero exit code. Typer rejects unrecognised `--output-root` option with usage error. |
| 4.2 | Grep across `src/` for `OutputConfig`, `output_root` (as a config field name), and `--output-root`. | Zero matches in production code. Only expected matches in test fixtures and documentation. |

## Phase 5: sdd to snapshot Rename

| Step | Action | Expected |
|------|--------|----------|
| 5.1 | Run `uv run pyaggregate run --type snapshot --config <valid_config>`. | Succeeds with exit code 0. Output appears under `{snapshot.output_path}/`. |
| 5.2 | Run `uv run pyaggregate run --type sdd --config <valid_config>`. | Non-zero exit code. Error message lists available agg types (which include `snapshot` but not `sdd`). |
| 5.3 | Grep across `src/` for `detect_sdd_collisions` or `sdd` as an agg type identifier. | Zero matches. Only `detect_snapshot_collisions` exists. |

## Phase 6: Example Config and Dead References

| Step | Action | Expected |
|------|--------|----------|
| 6.1 | Run `uv run python -c "from pyaggregate.config import load_config; from pathlib import Path; c = load_config(Path('pyaggregate.example.toml')); print(list(c.agg_types.keys()))"`. | Prints `['qa', 'qm', 'snapshot']` without errors. |
| 6.2 | Run `grep -rn "OutputConfig" src/ tests/` and `grep -rn "detect_sdd" src/ tests/`. | `OutputConfig`: zero matches everywhere. `detect_sdd`: zero matches (only `detect_snapshot` exists). |

## End-to-End: Full Pipeline Cold Start

**Purpose:** Validates that a brand-new user can init, scan, and run the full pipeline with all three agg types writing to independent output directories.

1. Create a fresh temp directory with synthetic requests tree (or use the project's test fixture builder).
2. Write a `pyaggregate.toml` with three `[agg.*]` blocks pointing to three separate output directories.
3. Run `uv run pyaggregate init-db --config pyaggregate.toml` -- expect exit code 0.
4. Run `uv run pyaggregate scan --config pyaggregate.toml` -- expect exit code 0.
5. Run `uv run pyaggregate run --config pyaggregate.toml` -- expect exit code 0.
6. Verify all three output directories contain `{run_id}/stacked/`, `{run_id}/masked/`, `{run_id}/dpid_map.csv`, and `latest -> {run_id}`.
7. Run `uv run pyaggregate run --config pyaggregate.toml --run-id rerun --force` -- expect exit code 0, outputs overwritten cleanly.

## End-to-End: Type-Filtered Run Isolation

**Purpose:** Validates that `--type` filtering produces outputs only for selected agg types without affecting others.

1. Using the same setup from the cold start scenario, run `uv run pyaggregate run --type qa --type snapshot --run-id filtered --config pyaggregate.toml`.
2. Verify `qa` and `snapshot` output directories contain `filtered/` run directories.
3. Verify `qm` output directory does NOT contain a `filtered/` directory.
4. Verify `qa/latest` and `snapshot/latest` symlinks point to `filtered`.
5. Verify `qm/latest` is unchanged from the previous run (or absent if qm was never run with this run_id).

## Human Verification Required

| Criterion | Why Manual | Steps |
|-----------|------------|-------|
| AC1.2 (distinct paths) | Structural correctness is easier to spot visually in a directory listing | `tree -L 3 {output_dir}` after a multi-agg run; confirm qa, qm, snapshot each have their own subtree with no shared `{agg_type}/{run_id}` pattern |
| AC3.2 (atomic symlink) | Atomicity under concurrent access cannot be reliably tested in pytest | During a long-running pipeline run, repeatedly `readlink {output_path}/latest` in another terminal; confirm it never returns an error or empty string |
| AC6.1 (no dead references) | Grep sweep is a point-in-time check; worth re-running before merge | `grep -rn "OutputConfig\|output_root\|--output-root\|detect_sdd" src/ tests/ \| grep -v CLAUDE.md \| grep -v test_run_sdd_rejected \| grep -v test_run_output_root_flag_rejected \| grep -v test_legacy_output_section_rejected` should produce only local variable names, not config field references |

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| AC1.1 | `test_load_valid_config`, `test_full_pipeline_ac9_1` | Phase 1 Step 1.1 |
| AC1.2 | `test_full_pipeline_ac9_1` (parent assertion), `test_run_with_type_filter_qa_snapshot_only` | End-to-End: Type-Filtered Run Isolation |
| AC1.3 | `test_output_path_tilde_expansion` | Phase 1 Step 1.4 |
| AC1.4 | `test_missing_output_path_rejected` | Phase 1 Step 1.3 |
| AC1.5 | `test_output_path_relative_preserved` | Phase 1 Step 1.5 |
| AC2.1 | `test_write_run_creates_directory_structure`, `test_write_run_dpid_map_filtered` | Phase 2 Step 2.1 |
| AC2.2 | `test_write_run_summary_json` | Phase 2 Step 2.2 |
| AC2.3 | `test_check_run_exists_returns_true`, `test_check_run_exists_returns_false` | Phase 2 Step 2.3 |
| AC2.4 | `test_run_partial_failure_exit_code_2`, `test_run_full_failure_exit_code_1` | -- (automated sufficient) |
| AC3.1 | `test_write_run_latest_symlink_created`, `test_full_pipeline_ac9_1` | Phase 3 Step 3.1 |
| AC3.2 | `test_write_run_atomic_symlink_update` | Phase 3 Step 3.2 (concurrent readlink) |
| AC3.3 | `test_run_with_type_filter_qa_snapshot_only`, `test_run_updates_latest_symlink_on_success` | Phase 3 Step 3.4 |
| AC4.1 | `test_legacy_output_section_rejected` | Phase 1 Step 1.2 |
| AC4.2 | `test_legacy_output_section_rejected` | Phase 4 Step 4.2 |
| AC4.3 | `test_run_output_root_flag_rejected_ac4_3` | Phase 4 Step 4.1 |
| AC5.1 | `test_run_with_type_filter_qa_snapshot_only`, `test_full_pipeline_ac9_1` | Phase 5 Step 5.1 |
| AC5.2 | `test_run_sdd_rejected_after_rename_ac5_2` | Phase 5 Step 5.2 |
| AC5.3 | `TestDetectSnapshotCollisions` (all tests) | Phase 5 Step 5.3 |
| AC6.1 | Full suite pass (202/202) + grep sweep | Phase 6 Step 6.2 |
| AC6.2 | `test_example_config_loadable_ac6_2` | Phase 6 Step 6.1 |
