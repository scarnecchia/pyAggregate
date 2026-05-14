# pyAggregate — Phase 8: End-to-end smoke test, logging, and operational documentation

**Goal:** Prove the whole system works end-to-end on synthetic data, finalize structured logging, and document the operational model so the SAS programs can be retired.

**Architecture:** Mixed — log_config.py is Imperative Shell (configures logging infrastructure). E2E test exercises the full CLI via subprocess. Docs are operational documentation for operators.

**Tech Stack:** Python 3.11+ stdlib (`logging`, `json`, `subprocess`), pytest

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield. Phases 1-7 create all pipeline components.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pyaggregate-unify-qa-qm-sdd.AC9: End-to-end smoke test passes
- **pyaggregate-unify-qa-qm-sdd.AC9.1 Success:** Starting from an empty state directory and a synthetic `requests/` tree, the sequence `pyaggregate init-db` -> `pyaggregate scan` -> `pyaggregate run` produces all expected output files for all three agg types with internally consistent row counts.
- **pyaggregate-unify-qa-qm-sdd.AC9.2 Success:** Re-running `pyaggregate run` with the same `--run-id` and `--force` overwrites the previous outputs cleanly.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Implement structured logging in log_config.py

**Files:**
- Create: `src/pyaggregate/log_config.py`

**Implementation:**

Create `src/pyaggregate/log_config.py` with `# pattern: Imperative Shell` on line 1.

Implement:
- `JsonFormatter` class extending `logging.Formatter`:
  - `format()` produces a single JSON line per log record
  - Standard fields: `timestamp` (UTC ISO 8601), `level`, `logger`, `message`
  - Extra fields merged from `record.__dict__` (table, run_id, dpid, etc.)
  - Uses relative paths in `source_path` fields — never absolute paths per programming standards

- `configure_logging(log_dir: Path | None, level: int = logging.INFO) -> None`:
  - Creates a `StreamHandler` to stderr with `JsonFormatter`
  - If `log_dir` is provided, creates a `FileHandler` writing to `<log_dir>/pyaggregate-YYYY-MM-DD.log` with `JsonFormatter`
  - Configures the root `pyaggregate` logger
  - Should be called once at CLI entry point

Modify `src/pyaggregate/cli.py` to call `configure_logging` in the typer callback (before any subcommand runs). Add `--verbose` flag for DEBUG level.

**Testing:**

No dedicated test file — logging is verified in the e2e test by checking log file existence and format.

**Verification:**

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No errors.

**Commit:** `feat: add JSON-lines structured logging`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Wire logging into scanner and pipeline

**Files:**
- Modify: `src/pyaggregate/io/scanner.py`
- Modify: `src/pyaggregate/core/pipeline.py`
- Modify: `src/pyaggregate/io/writer.py`

**Implementation:**

Add `logging.getLogger(__name__)` to each module. Emit structured log events at key points:

Scanner:
- `log.info("scan started", extra={"scan_id": scan_id})`
- `log.warning("unparseable package directory", extra={"dirname": dirname})` (AC2.5)
- `log.info("scan complete", extra={"scan_id": scan_id, "rows_upserted": N, "packages_skipped": N})`

Pipeline:
- `log.info("aggregating table", extra={"table": table_name, "agg_type": agg_type, "input_count": N})`
- `log.warning("sdd file collision", extra={"table": table_name, "dpid": dpid, "filename": filename})` (AC6.3)
- `log.info("table aggregated", extra={"table": table_name, "stacked_rows": N, "masked_rows": N})`

Writer:
- `log.info("writing output", extra={"agg_type": agg_type, "run_id": run_id, "table": table_name})`
- `log.info("symlink updated", extra={"agg_type": agg_type, "target": run_id})`

**Testing:**

No dedicated test — verified via e2e test log output.

**Verification:**

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No errors.

**Commit:** `feat: add structured logging throughout pipeline`

<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->

<!-- START_TASK_3 -->
### Task 3: Create synthetic SAS test fixtures

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/builders.py`

**Implementation:**

Create a test fixture builder module that generates synthetic `.sas7bdat` files for the e2e test. Since `polars-readstat` reads SAS files but polars cannot write them, use one of these approaches:

**Option A (preferred if available):** Use `pyreadstat` (add as dev dependency) to write small synthetic SAS files:
```python
import pyreadstat
df_pd = pd.DataFrame({"patid": [1, 2, 3], "enr_start": [18262.0, 18262.0, 18262.0]})
pyreadstat.write_sas7bdat(df_pd, str(path))
```

**Option B (if pyreadstat unavailable):** Create parquet fixtures instead and add a test-mode path in `sas_reader.py` that reads parquet files with the `.sas7bdat` extension as a fallback. This is a test-only concern — production code always reads real SAS files.

**Option C:** Use the `ReadStat` C library directly via the `readstat` package.

The implementor should evaluate which option is available in the environment. Option A is cleanest.

Implement a `build_requests_tree(root: Path, spec: list[DPSpec]) -> None` function that:
- Creates the full `requests/{qa,qm}/<dpid>/packages/...` directory tree
- Places synthetic `.sas7bdat` files in the correct `msoc/` and `msoc/scdm_snapshot/` locations
- Supports specifying which DPs have approved vs unapproved packages
- Supports specifying which DPs have `scdm_snapshot/` directories

The spec should cover at least 3 DPs with:
- Mixed approved/unapproved versions
- At least one DP with both qar and qmr packages
- At least one DP with scdm_snapshot
- At least 2 tables per DP (e.g., `ae` and `dem`)

**Testing:**

No dedicated test — the builder is tested by its usage in the e2e test.

**Verification:**

Run: `ruff check tests/ && ruff format --check tests/`

Expected: No errors.

**Commit:** `test: add synthetic SAS fixture builders for e2e testing`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Implement end-to-end smoke test

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC9.1, pyaggregate-unify-qa-qm-sdd.AC9.2

**Files:**
- Create: `tests/test_e2e_smoke.py`

**Implementation:**

Create `tests/test_e2e_smoke.py` marked with `@pytest.mark.integration`.

The test:
1. Constructs a `tmp_path` `requests/` tree with 3 synthetic DPs using the fixture builder from Task 3:
   - DP `aeos`: qar approved (v02), qar unapproved (v01 with msoc_new), qmr approved (v01), both with scdm_snapshot
   - DP `cms`: qar approved (v01), no qmr, no scdm_snapshot
   - DP `kpsc`: qar approved (v01), qmr approved (v01), qar has scdm_snapshot, qmr does not

2. Constructs a `pyaggregate.toml` in `tmp_path` pointing at the requests tree and output directory.

3. Runs real CLI commands via `subprocess.run`:
   ```python
   subprocess.run(["pyaggregate", "init-db", "--config", str(config_path)], check=True)
   subprocess.run(["pyaggregate", "scan", "--config", str(config_path)], check=True)
   subprocess.run(["pyaggregate", "run", "--config", str(config_path)], check=True)
   ```

4. Asserts:
   - AC9.1: All expected output files exist for all three agg types (`qa`, `qm`, `sdd`)
   - `latest` symlinks resolve correctly for each agg type
   - Stacked row counts are consistent (qa stacked has rows from all qar DPs)
   - Masked row counts equal stacked row counts
   - Rollup row counts <= stacked row counts
   - `dpid_map.csv` exists in each run directory and matches surrogates in masked outputs
   - No `.tmp` files survive

5. Re-run test (AC9.2):
   ```python
   subprocess.run([
       "pyaggregate", "run", "--config", str(config_path),
       "--run-id", run_id, "--force",
   ], check=True)
   ```
   - Verify outputs are overwritten cleanly
   - Verify row counts are still consistent

**Testing:**

This IS the test. It exercises the full pipeline end-to-end.

**Verification:**

Run: `pytest tests/test_e2e_smoke.py -v`

Expected: All tests pass.

**Commit:** `test: add end-to-end smoke test`

<!-- END_TASK_4 -->

<!-- END_SUBCOMPONENT_B -->

<!-- START_TASK_5 -->
### Task 5: Create operational documentation

**Files:**
- Create: `docs/operations.md`
- Create: `docs/migration.md`

**Implementation:**

Create `docs/operations.md` covering:
- Cron entries: `*/15 * * * * flock -n /var/run/pyaggregate-scan.lock pyaggregate scan --config /path/to/pyaggregate.toml` and `0 3 * * 0 pyaggregate run --config /path/to/pyaggregate.toml`
- State directory layout: catalog.db, logs, lockfile
- Backup procedure: nightly `cp catalog.db catalog.db.bak`
- Rollback procedure: `ln -sfn <previous-date> outputs/<agg>/latest`
- Log inspection: `jq . < logs/pyaggregate-YYYY-MM-DD.log` for structured log querying
- Monitoring: what to alert on (non-zero exit codes, scan log failures, row count drops)

Create `docs/migration.md` covering:
- One-time parity verification process
- Run pyaggregate against the same week's input as a recent SAS run
- Compare outputs: row counts per table, column schemas, numeric value sums
- Reconciliation steps for known discrepancies (date format differences, column ordering)
- SAS program retirement checklist: verify parity → shadow run for 2 weeks → cutover → archive SAS programs

**Testing:**

No tests — documentation only.

**Verification:**

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No errors.

Run: `pytest tests/ -v`

Expected: All tests pass (full suite).

**Commit:** `docs: add operations and migration documentation`

<!-- END_TASK_5 -->
