# pyAggregate: Test Requirements Matrix

Maps each acceptance criterion to specific automated tests or human verification steps.

---

## AC1: Package installs and CLI is reachable

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC1.1 | `pip install -e .` succeeds on python 3.11.x, 3.12.x, and 3.13.x with no `uv`-related errors. | Human / CI matrix | N/A | See human verification below. |
| pyaggregate-unify-qa-qm-sdd.AC1.2 | `pyaggregate --help` exits 0 and lists subcommands `scan`, `run`, `init-db`, `show-catalog`, `show-dpid-map`, `show-scans`. | E2E | `tests/test_e2e_smoke.py` | Subprocess call to `pyaggregate --help` exits 0; stdout contains all six subcommand names. |
| pyaggregate-unify-qa-qm-sdd.AC1.3 | `pip install -e .` on python 3.10 surfaces a clear "requires python >=3.11" error from pip metadata, not a runtime traceback. | Human | N/A | See human verification below. |

**Human verification (AC1.1):** Run `pip install -e .` in CI matrix jobs targeting python 3.11.x, 3.12.x, and 3.13.x. Confirm each succeeds with exit code 0 and no `uv`-related error output. This requires a multi-version CI environment (e.g., GitHub Actions matrix) which is infrastructure, not an in-repo test.

**Human verification (AC1.3):** On a python 3.10 environment, run `pip install -e .` and confirm the error message references `requires-python` metadata (`>=3.11`), not a runtime `SyntaxError` or `ImportError`. This is a one-time verification at project setup, not a recurring automated test.

---

## AC2: Scanner correctly maintains the catalog

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC2.1 | Given a tree where `aeos` has `soc_qar_wp041_aeos_v01/msoc/` AND `soc_qar_wp041_aeos_v02/msoc/`, the catalog row for `(aeos, wp041, qar)` references `v02`'s msoc path. | Unit + Integration | `tests/test_paths.py`, `tests/test_scanner.py` | `test_paths.py`: `pick_latest_approved` with two approved versions returns the `v02` RequestId. `test_scanner.py`: builds a `tmp_path` tree with v01 and v02, runs scanner, asserts catalog row points to v02. |
| pyaggregate-unify-qa-qm-sdd.AC2.2 | Given a tree where `aeos/soc_qar_wp041_aeos_v01/` contains only `msoc_new/` (failed QA), the scanner does NOT create a catalog row for `(aeos, wp041, qar)`. | Unit + Integration | `tests/test_paths.py`, `tests/test_scanner.py` | `test_paths.py`: `pick_latest_approved` with all `has_msoc=False` returns `None`. `test_scanner.py`: builds tree with only `msoc_new/`, asserts no catalog row exists for that `(dpid, wpid, reqtype)`. |
| pyaggregate-unify-qa-qm-sdd.AC2.3 | Running `pyaggregate scan` twice in succession against an unchanged tree produces zero net catalog changes (verified via `observed_at` being the only changed field, or by comparing snapshots). | Integration | `tests/test_scanner.py`, `tests/test_catalog_store.py` | `test_scanner.py`: runs scanner twice on same tree, snapshots catalog after each, asserts all non-`observed_at` fields are identical. `test_catalog_store.py`: UPSERT idempotence — same values twice, only `observed_at` changes. |
| pyaggregate-unify-qa-qm-sdd.AC2.4 | `has_scdm = 1` is set on rows whose `msoc/scdm_snapshot/` exists, `0` otherwise. | Integration | `tests/test_scanner.py` | Builds tree where one DP has `msoc/scdm_snapshot/` and another does not. Asserts catalog rows have correct `has_scdm` values. |
| pyaggregate-unify-qa-qm-sdd.AC2.5 | A package directory with an unparseable name (e.g., `soc_qar_wp041_aeos/` missing the verid suffix) is logged at WARN and skipped without aborting the scan. | Unit + Integration | `tests/test_paths.py`, `tests/test_scanner.py` | `test_paths.py`: `parse_request_id("soc_qar_wp041_aeos")` returns `None`. `test_scanner.py`: adds a malformed directory alongside valid ones, asserts valid rows are still catalogued and the scan completes without error. Uses `caplog` to verify WARN-level message. |
| pyaggregate-unify-qa-qm-sdd.AC2.6 | A second concurrent `pyaggregate scan` invocation while one is already running exits 0 with a "scan already in progress" log message (flock contention is handled, not crashed on). | Unit | `tests/test_scanner_concurrency.py` | Acquires flock in the test process, attempts second acquisition, asserts it returns `None`. Verifies the scanner exit-code-0 path when lock is already held. |

---

## AC3: Aggregation produces the three expected outputs per table

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC3.1 | For each table in the `qa` config, `outputs/qa/<run_id>/stacked/<table>.parquet` exists and contains rows from every catalog row where `reqtype = 'qar'`. | Integration | `tests/test_pipeline_stacked.py`, `tests/test_input_resolution.py`, `tests/test_e2e_smoke.py` | `test_input_resolution.py`: `qa` config filters to only `qar` rows. `test_pipeline_stacked.py`: 3 DPs each contributing 5 rows produces 15 stacked rows with all 3 dpids. `test_e2e_smoke.py`: verifies parquet files exist and row counts match expected. |
| pyaggregate-unify-qa-qm-sdd.AC3.2 | Stacked output preserves the real `dpid` column with values matching catalog `dpid`s. | Unit | `tests/test_pipeline_stacked.py` | Asserts stacked DataFrame has a `dpid` column and its unique values match the input DPIDs. |
| pyaggregate-unify-qa-qm-sdd.AC3.3 | `outputs/qa/<run_id>/masked/<table>.parquet` row count equals stacked row count, contains a `surrogate_id` column, and contains NO column named `dpid`. | Unit + Property | `tests/test_dpid_mask.py`, `tests/test_pipeline_stacked.py` | `test_dpid_mask.py`: hypothesis property tests assert row count preservation, `surrogate_id` presence, and `dpid` absence. `test_pipeline_stacked.py`: masked row count equals stacked row count. |
| pyaggregate-unify-qa-qm-sdd.AC3.4 | `outputs/qa/<run_id>/rollup/<table>.parquet` contains no `dpid` and no `surrogate_id` columns; sum over numeric columns equals the corresponding sum in stacked. | Unit + Property | `tests/test_pipeline_rollup.py` | Hypothesis property tests: rollup columns exclude `dpid` and `surrogate_id`; numeric column sums match stacked sums (within `pytest.approx` tolerance). |
| pyaggregate-unify-qa-qm-sdd.AC3.5 | Rollup row count is less than or equal to stacked row count (collapses identical key combinations across DPs). | Property | `tests/test_pipeline_rollup.py` | Hypothesis property test: for any synthetic DataFrame, `rollup.height <= stacked.height`. Example tests: identical keys collapse to 1 row; distinct keys preserve row count. |
| pyaggregate-unify-qa-qm-sdd.AC3.6 | All output files are written via temp-then-rename -- no `.tmp` files survive a successful run. | Integration | `tests/test_writer.py`, `tests/test_e2e_smoke.py` | `test_writer.py`: after `write_run`, recursively globs output tree for `*.tmp` and asserts empty. `test_e2e_smoke.py`: same glob assertion after full CLI run. |
| pyaggregate-unify-qa-qm-sdd.AC3.7 | Adding `--type qa --type sdd` produces only `qa` and `sdd` output trees; `qm` is untouched. | Integration | `tests/test_run_orchestration.py` | Runs orchestration with `type=["qa", "sdd"]`, asserts `qa/` and `sdd/` directories exist, `qm/` directory does not. |

---

## AC4: Catalog and run flags support adhoc / backfill use

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC4.1 | `pyaggregate run --catalog /tmp/alt.db` reads from the alternate catalog and ignores the configured default. | Integration | `tests/test_run_orchestration.py` | Creates two catalog databases with different contents, runs with `--catalog` pointing at the alternate, asserts outputs reflect the alternate catalog's data. |
| pyaggregate-unify-qa-qm-sdd.AC4.2 | `pyaggregate run --output-root /tmp/out` writes outputs under `/tmp/out` and does not touch the configured `output_root`. | Integration | `tests/test_run_orchestration.py` | Runs with `--output-root` pointing at a separate `tmp_path`, asserts outputs exist there and the default output_root is empty. |
| pyaggregate-unify-qa-qm-sdd.AC4.3 | `pyaggregate run --no-update-latest` produces a complete run directory but does NOT modify the existing `outputs/<agg>/latest` symlink. | Integration | `tests/test_writer.py`, `tests/test_run_orchestration.py` | `test_writer.py`: calls `write_run` with `update_latest=False`, asserts no `latest` symlink exists. `test_run_orchestration.py`: creates a pre-existing `latest` symlink, runs with `--no-update-latest`, asserts symlink still points at the original target. |
| pyaggregate-unify-qa-qm-sdd.AC4.4 | `pyaggregate run --run-id 2026-05-14-rerun` writes to a directory of that name; combined with `--no-update-latest` allows producing parallel reruns without disturbing prod. | Integration | `tests/test_run_orchestration.py` | Runs with `--run-id 2026-05-14-rerun`, asserts output directory is named `2026-05-14-rerun`. Combined with `--no-update-latest`, asserts existing `latest` symlink is undisturbed. |
| pyaggregate-unify-qa-qm-sdd.AC4.5 | `pyaggregate run --run-id <existing>` without `--force` exits non-zero with a "run directory already exists" error and writes nothing. | Integration | `tests/test_run_orchestration.py` | Creates a run directory manually, runs without `--force`, asserts non-zero exit code and error message. With `--force`, asserts successful overwrite. |

---

## AC5: DPID surrogate mapping is stable and auto-extending

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC5.1 | A DPID seen in a previous run receives the same surrogate_id in subsequent runs (across multiple `run` invocations spanning multiple scans). | Unit | `tests/test_catalog_store.py`, `tests/test_dpid_mask.py` | `test_catalog_store.py`: calling `get_or_create_surrogate("aeos")` twice returns the same value. `test_dpid_mask.py`: example test with known dpid_map produces expected surrogate values. |
| pyaggregate-unify-qa-qm-sdd.AC5.2 | A newly-observed DPID receives a fresh surrogate_id never previously assigned, and is added to `dpid_map` automatically. | Unit | `tests/test_catalog_store.py` | Calling `get_or_create_surrogate` with a new DPID returns a fresh surrogate (`dp_002` after `dp_001`). The surrogate is unique and monotonically increasing. |
| pyaggregate-unify-qa-qm-sdd.AC5.3 | Each run directory contains a `dpid_map.csv` whose contents exactly correspond to the surrogates present in that run's `masked/` outputs. | Integration | `tests/test_writer.py`, `tests/test_e2e_smoke.py` | `test_writer.py`: reads the written `dpid_map.csv`, extracts surrogate_ids from all masked parquet files, asserts the sets are identical. `test_e2e_smoke.py`: same assertion after full CLI run. |

---

## AC6: SDD aggregation pulls from both qar and qmr packages

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC6.1 | Given a DP with both `soc_qar_wp041_<dp>_v01/msoc/scdm_snapshot/` and `soc_qmr_wp041_<dp>_v01/msoc/scdm_snapshot/` populated with complementary file sets, the SDD output contains rows derived from BOTH subtrees. | Integration | `tests/test_input_resolution.py`, `tests/test_e2e_smoke.py` | `test_input_resolution.py`: `sdd` config resolves both qar and qmr scdm_snapshot paths for the same DP. `test_e2e_smoke.py`: SDD stacked output row count reflects contributions from both reqtypes. |
| pyaggregate-unify-qa-qm-sdd.AC6.2 | Given a DP where only the qar package's scdm_snapshot exists (qmr not yet returned), SDD includes the qar contribution and does not error on the missing qmr side. | Integration | `tests/test_input_resolution.py`, `tests/test_e2e_smoke.py` | `test_input_resolution.py`: catalog with only qar `has_scdm=1` for a DP resolves without error. `test_e2e_smoke.py`: DP `kpsc` has qar scdm_snapshot but no qmr scdm_snapshot; SDD output includes kpsc's qar contribution. |
| pyaggregate-unify-qa-qm-sdd.AC6.3 | If a file with the same name appears in BOTH the qar and qmr scdm_snapshot for the same `(dpid, wpid)` (collision rather than complementary), the run logs a WARN naming the conflicting file and includes both rows in stacked output (no silent dedup). | Unit | `tests/test_input_resolution.py` | `detect_sdd_collisions` given inputs with same filename from both reqtypes returns warning messages naming the conflicting file. Stacked output includes rows from both sources (row count is sum of both). |

---

## AC7: `*_stats` exclusion applies to rollup only

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC7.1 | Tables matching any pattern in `agg.<type>.exclude_from_rollup` produce `stacked.parquet` and `masked.parquet` but NO `rollup.parquet`. | Unit + Integration | `tests/test_stats_exclusion.py`, `tests/test_writer.py` | `test_stats_exclusion.py`: `should_exclude_rollup("ae_stats", ("*_stats",))` returns `True`; `aggregate_table` output dict for excluded table has `stacked` and `masked` keys but no `rollup`. `test_writer.py`: stats-excluded table produces stacked + masked directories but no rollup directory/file. |
| pyaggregate-unify-qa-qm-sdd.AC7.2 | Non-matching tables in the same agg_type produce all three outputs. | Unit | `tests/test_stats_exclusion.py` | `should_exclude_rollup("ae", ("*_stats",))` returns `False`; `aggregate_table` output dict for non-excluded table has all three keys (`stacked`, `masked`, `rollup`). |

---

## AC8: `latest` symlink is always valid

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC8.1 | After a successful run with `update_latest=True`, `outputs/<agg>/latest` resolves to the just-written `<run_id>` directory. | Integration | `tests/test_writer.py`, `tests/test_e2e_smoke.py` | `test_writer.py`: after `write_run` with `update_latest=True`, `os.readlink(latest)` returns the `run_id`. `test_e2e_smoke.py`: `latest` symlinks resolve to the run directory for each agg type. |
| pyaggregate-unify-qa-qm-sdd.AC8.2 | The symlink update is atomic -- at no observable point during the swap is `outputs/<agg>/latest` missing or pointing at a nonexistent target. (Verified by polling during the writer's symlink-update operation in a test.) | Integration | `tests/test_writer.py` | Creates a pre-existing `latest` symlink pointing at run A. Calls `write_run` for run B. Asserts: (1) after the call, `latest` points to run B; (2) the implementation uses the `symlink-to-tempname-then-rename` pattern (verified by inspecting the writer code or by checking that `latest` was never absent during the operation). |

**Note on AC8.2 atomicity testing:** True concurrent-poll testing of symlink atomicity is inherently racy in a single-threaded test. The primary verification is code review of the `symlink-to-tempname-then-rename` pattern in `writer.py`. The test verifies the outcome (correct target after update) and the absence of stale temp symlinks, which together provide strong evidence of the atomic pattern.

---

## AC9: End-to-end smoke test passes

| AC ID | AC Text | Test Type | Test File | What the Test Verifies |
|---|---|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC9.1 | Starting from an empty state directory and a synthetic `requests/` tree, the sequence `pyaggregate init-db` -> `pyaggregate scan` -> `pyaggregate run` produces all expected output files for all three agg types with internally consistent row counts. | E2E | `tests/test_e2e_smoke.py` | Builds a 3-DP synthetic requests tree in `tmp_path`. Runs `init-db`, `scan`, `run` via `subprocess.run`. Asserts: all parquet files exist under `qa/`, `qm/`, `sdd/`; `latest` symlinks resolve; stacked row counts match expected DP contributions; masked row counts equal stacked; rollup row counts <= stacked; `dpid_map.csv` matches masked surrogates; no `.tmp` files survive. |
| pyaggregate-unify-qa-qm-sdd.AC9.2 | Re-running `pyaggregate run` with the same `--run-id` and `--force` overwrites the previous outputs cleanly. | E2E | `tests/test_e2e_smoke.py` | After the initial run (AC9.1), re-runs `pyaggregate run --run-id <same> --force`. Asserts: outputs are overwritten; row counts remain consistent; no stale files from previous run leak through. |

---

## Summary: Test File to AC Mapping

| Test File | ACs Covered |
|---|---|
| `tests/test_paths.py` | AC2.1, AC2.2, AC2.5 |
| `tests/test_config.py` | AC1.1, AC1.2 |
| `tests/test_catalog_store.py` | AC2.3, AC5.1, AC5.2 |
| `tests/test_scanner.py` | AC2.1, AC2.2, AC2.3, AC2.4, AC2.5 |
| `tests/test_scanner_concurrency.py` | AC2.6 |
| `tests/test_input_resolution.py` | AC3.1, AC6.1, AC6.2, AC6.3 |
| `tests/test_dpid_mask.py` | AC3.3, AC5.1, AC5.2 |
| `tests/test_pipeline_stacked.py` | AC3.1, AC3.2, AC3.3 |
| `tests/test_pipeline_rollup.py` | AC3.4, AC3.5 |
| `tests/test_stats_exclusion.py` | AC7.1, AC7.2 |
| `tests/test_writer.py` | AC3.6, AC4.3, AC5.3, AC7.1, AC8.1, AC8.2 |
| `tests/test_run_orchestration.py` | AC3.7, AC4.1, AC4.2, AC4.3, AC4.4, AC4.5 |
| `tests/test_e2e_smoke.py` | AC1.2, AC3.1, AC3.6, AC5.3, AC6.1, AC6.2, AC8.1, AC9.1, AC9.2 |
| Human / CI matrix | AC1.1, AC1.3 |

## ACs Requiring Human Verification

| AC ID | Reason Automation Is Insufficient | Human Verification Approach |
|---|---|---|
| pyaggregate-unify-qa-qm-sdd.AC1.1 | Requires running `pip install` across three Python versions (3.11, 3.12, 3.13). This is CI matrix infrastructure, not an in-repo pytest test. | Configure CI matrix (GitHub Actions or equivalent) with python-version: [3.11, 3.12, 3.13]. Each job runs `pip install -e .` and `pyaggregate --help`. Inspect CI logs for `uv`-related errors. |
| pyaggregate-unify-qa-qm-sdd.AC1.3 | Requires a Python 3.10 environment to confirm pip metadata rejection. Negative-version testing is a one-time setup verification. | On a python 3.10 venv, run `pip install -e .`. Confirm error message contains `requires-python` and references `>=3.11`. Document the output once and archive. |
| pyaggregate-unify-qa-qm-sdd.AC8.2 | True atomicity is a code-level guarantee (symlink-then-rename pattern), not something a sequential test can fully prove. | Code review: verify `writer.py` uses `os.symlink(target, tmp_name)` followed by `os.rename(tmp_name, latest_path)`. The test in `test_writer.py` verifies the outcome and absence of stale temp symlinks. |
