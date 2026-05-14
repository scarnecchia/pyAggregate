# pyAggregate — Phase 7: Writer, run orchestration, and `latest` symlink

**Goal:** Wire pipeline outputs to disk in the agreed layout, manage the `latest` symlink, write the dpid_map sidecar, and orchestrate per-run execution end-to-end.

**Architecture:** Imperative Shell — writer handles all file I/O (parquet writes, symlink management). CLI `run` command orchestrates the full pipeline: catalog snapshot → input resolution → per-table aggregation → write outputs.

**Tech Stack:** Python 3.11+ stdlib (`os`, `pathlib`, `tempfile`), polars (`write_parquet`, `write_csv`)

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield. Phases 1-6 create all pipeline components.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pyaggregate-unify-qa-qm-sdd.AC3: Aggregation produces the three expected outputs per table
- **pyaggregate-unify-qa-qm-sdd.AC3.6 Success:** All output files are written via temp-then-rename — no `.tmp` files survive a successful run.
- **pyaggregate-unify-qa-qm-sdd.AC3.7 Success:** Adding `--type qa --type sdd` produces only `qa` and `sdd` output trees; `qm` is untouched.

### pyaggregate-unify-qa-qm-sdd.AC4: Catalog and run flags support adhoc / backfill use
- **pyaggregate-unify-qa-qm-sdd.AC4.3 Success:** `pyaggregate run --no-update-latest` produces a complete run directory but does NOT modify the existing `outputs/<agg>/latest` symlink.
- **pyaggregate-unify-qa-qm-sdd.AC4.4 Success:** `pyaggregate run --run-id 2026-05-14-rerun` writes to a directory of that name; combined with `--no-update-latest` allows producing parallel reruns without disturbing prod.
- **pyaggregate-unify-qa-qm-sdd.AC4.5 Failure:** `pyaggregate run --run-id <existing>` without `--force` exits non-zero with a "run directory already exists" error and writes nothing.

### pyaggregate-unify-qa-qm-sdd.AC5: DPID surrogate mapping is stable and auto-extending
- **pyaggregate-unify-qa-qm-sdd.AC5.3 Success:** Each run directory contains a `dpid_map.csv` whose contents exactly correspond to the surrogates present in that run's `masked/` outputs.

### pyaggregate-unify-qa-qm-sdd.AC8: `latest` symlink is always valid
- **pyaggregate-unify-qa-qm-sdd.AC8.1 Success:** After a successful run with `update_latest=True`, `outputs/<agg>/latest` resolves to the just-written `<run_id>` directory.
- **pyaggregate-unify-qa-qm-sdd.AC8.2 Success:** The symlink update is atomic — at no observable point during the swap is `outputs/<agg>/latest` missing or pointing at a nonexistent target. (Verified by polling during the writer's symlink-update operation in a test.)

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Implement writer in io/writer.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.6, pyaggregate-unify-qa-qm-sdd.AC5.3, pyaggregate-unify-qa-qm-sdd.AC8.1, pyaggregate-unify-qa-qm-sdd.AC8.2

**Files:**
- Create: `src/pyaggregate/io/writer.py`

**Implementation:**

Create `src/pyaggregate/io/writer.py` with `# pattern: Imperative Shell` on line 1.

Implement `write_run(output_root: Path, agg_type: str, run_id: str, table_outputs: dict[str, dict[str, polars.DataFrame]], dpid_map_frame: polars.DataFrame, update_latest: bool) -> None`:

1. Create directory structure: `output_root/<agg_type>/<run_id>/<output_type>/` for each output type (stacked, masked, rollup). Before writing, glob and remove any orphaned `*.tmp` files from a previous interrupted run in this run directory (cheap insurance against SIGKILL/OOM leaving stale temp files).

2. For each table and its output dict:
   - Write each DataFrame to `<path>.tmp` first via `df.write_parquet(<path>.tmp)`
   - Then `os.rename(<path>.tmp, <path>)` for atomicity (AC3.6)
   - Only write `rollup` if present in the output dict (stats-excluded tables won't have it)

3. Write `dpid_map.csv` to `output_root/<agg_type>/<run_id>/dpid_map.csv` via temp-then-rename.
   - Filter dpid_map to only include surrogates actually used in this run's masked outputs (AC5.3).

3b. Write `run_summary.json` to `output_root/<agg_type>/<run_id>/run_summary.json` via temp-then-rename. Contains: `run_id`, `agg_type`, `started_at`, `ended_at`, `tables_succeeded` (list of table names), `tables_skipped` (list of `{table, error_class, detail}`), `exit_code`. This provides operators an immediate structured artifact to identify failures without parsing logs.

4. If `update_latest=True`, atomically update the `latest` symlink:
   - Create symlink to a temp name: `os.symlink(run_id, latest_tmp)` where `latest_tmp` is `latest.<random>` in the same directory
   - Atomic rename: `os.rename(latest_tmp, latest_path)` — POSIX rename is atomic for symlinks (AC8.2)
   - The symlink uses a relative target (`run_id` not full path) so it works if the output tree is moved

Also implement `check_run_exists(output_root: Path, agg_type: str, run_id: str) -> bool` for the `--force` guard.

**Testing:**

Tests must verify:
- AC3.6: After write, no `.tmp` files exist in the output tree
- AC5.3: `dpid_map.csv` contains only surrogates present in that run's masked outputs
- AC8.1: `latest` symlink resolves to the run_id directory
- AC8.2: Symlink is always valid (create a pre-existing symlink, update it, verify no window where it's broken)
- File layout: correct directory structure with expected files

Follow project testing patterns. Use `tmp_path`.

**Verification:**

Run: `pytest tests/test_writer.py -v`

Expected: All tests pass.

**Commit:** `feat: add parquet writer with atomic temp-rename and symlink management`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Test writer

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.6, pyaggregate-unify-qa-qm-sdd.AC5.3, pyaggregate-unify-qa-qm-sdd.AC8.1, pyaggregate-unify-qa-qm-sdd.AC8.2

**Files:**
- Create: `tests/test_writer.py`

**Testing:**

Create synthetic table_outputs dict for testing:

```python
table_outputs = {
    "ae": {
        "stacked": pl.DataFrame({"dpid": ["aeos", "cms"], "col1": [1, 2]}),
        "masked": pl.DataFrame({"surrogate_id": ["dp_001", "dp_002"], "col1": [1, 2]}),
        "rollup": pl.DataFrame({"col1": [3]}),
    },
    "ae_stats": {
        "stacked": pl.DataFrame({"dpid": ["aeos"], "col1": [1]}),
        "masked": pl.DataFrame({"surrogate_id": ["dp_001"], "col1": [1]}),
        # No "rollup" key — excluded by _stats pattern
    },
}
```

Tests must cover:
- File layout: `output_root/qa/2026-05-14/stacked/ae.parquet` exists
- No `.tmp` files survive (AC3.6)
- `dpid_map.csv` matches surrogates in masked outputs (AC5.3)
- `latest` symlink points to `2026-05-14` (AC8.1)
- Atomic symlink update: create initial symlink → update → verify never broken (AC8.2)
- `update_latest=False`: no symlink created/modified (AC4.3)
- Stats-excluded table: `ae_stats` has stacked + masked dirs but no rollup dir
- `check_run_exists` returns True for existing run directory

**Verification:**

Run: `pytest tests/test_writer.py -v`

Expected: All tests pass.

**Commit:** `test: add writer tests for atomic writes, symlinks, and dpid_map`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Wire run command into CLI

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.7, pyaggregate-unify-qa-qm-sdd.AC4.3, pyaggregate-unify-qa-qm-sdd.AC4.4, pyaggregate-unify-qa-qm-sdd.AC4.5

**Files:**
- Modify: `src/pyaggregate/cli.py`

**Implementation:**

Replace the `run` stub with the full implementation:

```python
@app.command()
def run(
    type: list[str] = typer.Option(None, "--type", help="Aggregation type(s) to run"),
    catalog: Path | None = typer.Option(None, help="Path to alternate catalog db"),
    output_root: Path | None = typer.Option(None, help="Path to alternate output root"),
    run_id: str | None = typer.Option(None, help="Custom run ID (default: today's date)"),
    no_update_latest: bool = typer.Option(False, help="Skip updating the latest symlink"),
    force: bool = typer.Option(False, help="Overwrite existing run directory"),
    config: Path | None = typer.Option(None, envvar="PYAGGREGATE_CONFIG"),
) -> None:
```

Logic:
1. Load config, resolve catalog_db (from `--catalog` or config), resolve output_root (from `--output-root` or config).
2. Default `run_id` to today's date (`YYYY-MM-DD`).
3. Determine which agg_types to run (from `--type` or all configured types).
4. For each agg_type:
   - Check if run directory exists. If yes and no `--force`, exit non-zero with error (AC4.5).
   - Open CatalogStore, snapshot catalog and dpid_map.
   - Resolve inputs via `resolve_inputs`.
   - For each table: call `aggregate_table` to produce outputs. Wrap in try/except — if a table fails (corrupted SAS file, read error), classify the exception via a `classify_exception(exc) -> ErrorClass` function (per programming standards section 4.3 — mapping to literals like `"source_missing"`, `"source_permission"`, `"parse_error"`, `"arrow_error"`, `"unknown"`), log with structured `error_class` field, record the table as skipped, and continue with remaining tables.
   - Call `write_run` to write outputs to disk.
5. Print summary of what was written.
6. Exit code: 0 if all tables succeeded, 2 if some tables were skipped (partial success), 1 if the run failed entirely. The non-zero exit on partial success ensures cron's mailto surfaces the issue (per design "Error handling" section).

**Testing:**

No new test file — CLI wiring is verified in Phase 8 e2e test and test_run_orchestration.

**Verification:**

Run: `pyaggregate run --help`

Expected: Shows all flags: `--type`, `--catalog`, `--output-root`, `--run-id`, `--no-update-latest`, `--force`.

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No errors.

**Commit:** `feat: wire run command with full flag support`

<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_4 -->
### Task 4: Test run orchestration

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.7, pyaggregate-unify-qa-qm-sdd.AC4.3, pyaggregate-unify-qa-qm-sdd.AC4.4, pyaggregate-unify-qa-qm-sdd.AC4.5

**Files:**
- Create: `tests/test_run_orchestration.py`

**Testing:**

Integration test: set up a synthetic catalog (via CatalogStore in `tmp_path`), mock the `reader_fn` to return synthetic DataFrames, run the full orchestration pipeline, verify output files.

Tests must cover:
- AC3.7: `--type qa --type sdd` produces only qa and sdd outputs, no qm directory
- AC4.3: `--no-update-latest` produces run directory but no `latest` symlink
- AC4.4: `--run-id 2026-05-14-rerun` produces directory with that name
- AC4.5: Existing run directory without `--force` → exit non-zero
- AC4.5: Existing run directory with `--force` → overwrites cleanly
- Default run_id is today's date in YYYY-MM-DD format
- All three agg types produce expected output files when no `--type` filter
- Partial failure: when one table read raises an exception, run completes with exit code 2, other tables still written
- Full failure: when all tables fail, run exits with code 1

**Verification:**

Run: `pytest tests/test_run_orchestration.py -v`

Expected: All tests pass.

Run: `pytest tests/ -v`

Expected: All Phase 1-7 tests pass.

**Commit:** `test: add run orchestration integration tests`

<!-- END_TASK_4 -->
