# pyAggregate — Phase 4: Scanner implementation

**Goal:** Walk the requests tree, populate the catalog with the latest approved msoc per `(dpid, wpid, reqtype)`.

**Architecture:** Imperative Shell — scanner walks the filesystem and calls CatalogStore methods. Uses `pick_latest_approved` from `core/paths.py` for version ranking.

**Tech Stack:** Python 3.11+ stdlib (`pathlib`, `fcntl`, `uuid`, `logging`), CatalogStore (Phase 3), paths.py (Phase 2)

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield. Phases 1-3 create scaffold, paths, config, and catalog store.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pyaggregate-unify-qa-qm-sdd.AC2: Scanner correctly maintains the catalog
- **pyaggregate-unify-qa-qm-sdd.AC2.1 Success:** Given a tree where `aeos` has `soc_qar_wp041_aeos_v01/msoc/` AND `soc_qar_wp041_aeos_v02/msoc/`, the catalog row for `(aeos, wp041, qar)` references `v02`'s msoc path.
- **pyaggregate-unify-qa-qm-sdd.AC2.2 Success:** Given a tree where `aeos/soc_qar_wp041_aeos_v01/` contains only `msoc_new/` (failed QA), the scanner does NOT create a catalog row for `(aeos, wp041, qar)`.
- **pyaggregate-unify-qa-qm-sdd.AC2.3 Success:** Running `pyaggregate scan` twice in succession against an unchanged tree produces zero net catalog changes (verified via `observed_at` being the only changed field, or by comparing snapshots).
- **pyaggregate-unify-qa-qm-sdd.AC2.4 Success:** `has_scdm = 1` is set on rows whose `msoc/scdm_snapshot/` exists, `0` otherwise.
- **pyaggregate-unify-qa-qm-sdd.AC2.5 Failure:** A package directory with an unparseable name (e.g., `soc_qar_wp041_aeos/` missing the verid suffix) is logged at WARN and skipped without aborting the scan.
- **pyaggregate-unify-qa-qm-sdd.AC2.6 Failure:** A second concurrent `pyaggregate scan` invocation while one is already running exits 0 with a "scan already in progress" log message (flock contention is handled, not crashed on).

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Implement scanner in io/scanner.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.1, AC2.2, AC2.3, AC2.4, AC2.5

**Files:**
- Create: `src/pyaggregate/io/scanner.py`

**Implementation:**

Create `src/pyaggregate/io/scanner.py` with `# pattern: Imperative Shell` on line 1.

Implement a `run_scan(config: AppConfig, store: CatalogStore) -> ScanResult` function that:

1. Generates a UUID scan_id, records scan start in scan_log.
2. Walks the requests tree structure: `requests_root/{qa,qm}/<dpid>/packages/`. Under each `packages/` directory, lists subdirectories matching the package name pattern.
3. For each `<dpid>/packages/` directory:
   - Lists all `soc_<reqtype>_<wpid>_*` subdirectories (the workplan level, e.g., `soc_qar_wp041/`)
   - Under each workplan directory, lists version subdirectories (e.g., `soc_qar_wp041_aeos_v01/`, `soc_qar_wp041_aeos_v02/`)
   - Parses each version directory name via `parse_request_id()`
   - Logs WARN and skips unparseable names (AC2.5)
   - For each parsed `RequestId`, checks whether `<version_dir>/msoc/` exists (I/O at the shell boundary)
   - Groups by `(dpid, wpid, reqtype)`, calls `pick_latest_approved()` with `(RequestId, has_msoc: bool)` tuples to find the highest approved version
   - For the winning version, checks for `msoc/scdm_snapshot/` existence to set `has_scdm`
   - UPSERTs the catalog row
   - Calls `store.get_or_create_surrogate(dpid)` to auto-extend dpid_map
4. Records scan end with success/failure status.
5. Returns a frozen dataclass `ScanResult` with counts: `rows_upserted`, `packages_skipped`, `errors`.

Also implement `run_scan_dry(config: AppConfig, store: CatalogStore) -> list[str]` that performs the same walk but only reports intended changes without writing.

**Testing:**

Tests must verify:
- AC2.1: Two versions, both with `msoc/`, scanner picks highest verid
- AC2.2: Only `msoc_new/` exists → no catalog row created
- AC2.3: Two identical scans produce same catalog snapshot (idempotence)
- AC2.4: `has_scdm` correctly reflects `msoc/scdm_snapshot/` presence
- AC2.5: Unparseable directory name logged at WARN, scan continues

Follow project testing patterns. Use `tmp_path` to construct directory trees.

**Verification:**

Run: `pytest tests/test_scanner.py -v`

Expected: All tests pass.

**Commit:** `feat: add filesystem scanner with version ranking and catalog upsert`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Test scanner

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.1, AC2.2, AC2.3, AC2.4, AC2.5

**Files:**
- Create: `tests/test_scanner.py`

**Testing:**

Create a helper function (or fixture) that builds a realistic `requests/` tree inside `tmp_path`. The builder should accept a specification like:

```python
# Example spec: (dpid, reqtype_dir, wpid, versions_with_msoc_status)
[
    ("aeos", "qa", "wp041", [("v01", "msoc"), ("v02", "msoc")]),
    ("aeos", "qa", "wp042", [("v01", "msoc_new")]),  # failed QA
    ("cms",  "qm", "wp041", [("v01", "msoc")]),
    ("cms",  "qa", "wp041", [("v01", "msoc")]),  # with scdm_snapshot
]
```

And create the directory tree:
```
requests/qa/aeos/packages/soc_qar_wp041/soc_qar_wp041_aeos_v01/msoc/
requests/qa/aeos/packages/soc_qar_wp041/soc_qar_wp041_aeos_v02/msoc/
requests/qa/aeos/packages/soc_qar_wp042/soc_qar_wp042_aeos_v01/msoc_new/
requests/qm/cms/packages/soc_qmr_wp041/soc_qmr_wp041_cms_v01/msoc/
requests/qa/cms/packages/soc_qar_wp041/soc_qar_wp041_cms_v01/msoc/scdm_snapshot/
```

Tests must cover:
- AC2.1: `aeos/wp041/qar` catalog row points to `v02` path (not `v01`)
- AC2.2: `aeos/wp042/qar` has NO catalog row (only `msoc_new/`)
- AC2.3: Run scanner twice, compare catalog snapshots — identical except `observed_at`
- AC2.4: `cms/wp041/qar` row has `has_scdm=1` (scdm_snapshot dir exists); `aeos/wp041/qar` has `has_scdm=0`
- AC2.5: Add a directory named `soc_qar_wp041_aeos` (no verid) — scanner warns and skips, other rows still created
- Multi-DP scan: 3+ DPs in one tree, all catalogued correctly

**Verification:**

Run: `pytest tests/test_scanner.py -v`

Expected: All tests pass.

**Commit:** `test: add scanner integration tests with directory tree fixtures`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Implement flock guard and test concurrency

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.6

**Files:**
- Modify: `src/pyaggregate/io/scanner.py`
- Create: `tests/test_scanner_concurrency.py`

**Implementation:**

Add a `acquire_scan_lock(lock_path: Path) -> int | None` function that:
- Opens `<catalog_db>.scan.lock` for writing
- Attempts `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`
- Returns the file descriptor on success, `None` on `BlockingIOError` (lock held by another process)

Wrap `run_scan` entry to acquire lock first. If lock acquisition fails, log "scan already in progress" and return early with exit code 0 (not an error).

**Testing:**

Tests must cover:
- AC2.6: Acquire lock in test, attempt second acquisition in same process → returns `None`
- Lock release: after releasing, second acquisition succeeds
- Scanner exits cleanly (exit code 0) when lock is held

Note: True multi-process flock testing is fragile in CI. Test the lock acquisition/release logic directly rather than spawning subprocesses.

**Verification:**

Run: `pytest tests/test_scanner_concurrency.py -v`

Expected: All tests pass.

**Commit:** `feat: add flock-based scan concurrency guard`

<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_4 -->
### Task 4: Wire scan command into CLI

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.1 through AC2.6 (via CLI invocation)

**Files:**
- Modify: `src/pyaggregate/cli.py`

**Implementation:**

Replace the `scan` stub in `cli.py` with a real implementation:
- Load config via `resolve_config_path` + `load_config`
- Open `CatalogStore`
- Call `run_scan(config, store)`
- Add `--dry-run` flag that calls `run_scan_dry` instead
- Print summary: rows upserted, packages skipped, errors
- Exit 0 on success, exit 1 on scan failure

**Testing:**

No new test file — CLI wiring is verified in Phase 8 e2e test.

**Verification:**

Run: `pyaggregate scan --help`

Expected: Shows help with `--dry-run` flag.

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No errors.

**Commit:** `feat: wire scan command with dry-run support`

<!-- END_TASK_4 -->
