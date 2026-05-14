# pyAggregate — Phase 3: Sqlite catalog store

**Goal:** Implement the catalog and dpid_map sqlite schema and the read/write API used by both scanner and aggregator.

**Architecture:** Imperative Shell — `CatalogStore` wraps sqlite connection and exposes methods for schema init, UPSERT, surrogate mapping, and snapshots.

**Tech Stack:** Python 3.11+ stdlib (`sqlite3`, `uuid`, `datetime`), polars

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield. Phase 1-2 create scaffold, paths, and config modules.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pyaggregate-unify-qa-qm-sdd.AC2: Scanner correctly maintains the catalog
- **pyaggregate-unify-qa-qm-sdd.AC2.3 Success:** Running `pyaggregate scan` twice in succession against an unchanged tree produces zero net catalog changes (verified via `observed_at` being the only changed field, or by comparing snapshots).

### pyaggregate-unify-qa-qm-sdd.AC4: Catalog and run flags support adhoc / backfill use
- **pyaggregate-unify-qa-qm-sdd.AC4.1 Success:** `pyaggregate run --catalog /tmp/alt.db` reads from the alternate catalog and ignores the configured default.
- **pyaggregate-unify-qa-qm-sdd.AC4.2 Success:** `pyaggregate run --output-root /tmp/out` writes outputs under `/tmp/out` and does not touch the configured `output_root`.

### pyaggregate-unify-qa-qm-sdd.AC5: DPID surrogate mapping is stable and auto-extending
- **pyaggregate-unify-qa-qm-sdd.AC5.1 Success:** A DPID seen in a previous run receives the same surrogate_id in subsequent runs (across multiple `run` invocations spanning multiple scans).
- **pyaggregate-unify-qa-qm-sdd.AC5.2 Success:** A newly-observed DPID receives a fresh surrogate_id never previously assigned, and is added to `dpid_map` automatically.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Implement CatalogStore

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.3, pyaggregate-unify-qa-qm-sdd.AC5.1, pyaggregate-unify-qa-qm-sdd.AC5.2

**Files:**
- Create: `src/pyaggregate/io/catalog_store.py`

**Implementation:**

Create `src/pyaggregate/io/catalog_store.py` with `# pattern: Imperative Shell` on line 1.

Implement a `CatalogStore` class wrapping a sqlite connection (WAL mode). Constructor takes `db_path: Path`, opens connection, sets WAL mode and foreign keys.

Methods:
- `init_schema() -> None` — creates `catalog`, `dpid_map`, `scan_log` tables using `CREATE TABLE IF NOT EXISTS`. Schema:
  ```sql
  CREATE TABLE catalog (
    dpid        TEXT NOT NULL,
    wpid        TEXT NOT NULL,
    reqtype     TEXT NOT NULL,
    verid       TEXT NOT NULL,
    msoc_path   TEXT NOT NULL,
    has_scdm    INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (dpid, wpid, reqtype)
  );
  CREATE TABLE dpid_map (
    dpid          TEXT PRIMARY KEY,
    surrogate_id  TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL
  );
  CREATE TABLE scan_log (
    scan_id     TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL,
    error_msg   TEXT
  );
  ```
- `upsert_catalog_row(dpid, wpid, reqtype, verid, msoc_path, has_scdm) -> None` — uses `INSERT ... ON CONFLICT(dpid, wpid, reqtype) DO UPDATE SET verid=excluded.verid, msoc_path=excluded.msoc_path, has_scdm=excluded.has_scdm, observed_at=excluded.observed_at`. Sets `observed_at` to current UTC ISO timestamp.
- `get_or_create_surrogate(dpid: str) -> str` — looks up `dpid_map` for existing surrogate. If not found, generates next sequential surrogate as `dp_NNN` (zero-padded to 3 digits, e.g., `dp_001`), inserts row with `first_seen_at`, returns it. The counter is derived from `SELECT COALESCE(MAX(CAST(SUBSTR(surrogate_id, 4) AS INTEGER)), 0) + 1 FROM dpid_map` to ensure monotonic assignment. The entire read+insert must execute within a single `BEGIN IMMEDIATE` transaction to prevent concurrent writers from generating duplicate surrogates. (In practice, sqlite WAL mode serialises writers, but explicit transaction isolation makes the guarantee structural rather than incidental. The `UNIQUE` constraint on `surrogate_id` provides a final safety net.)
- `snapshot_catalog() -> polars.DataFrame` — reads entire catalog table into a polars DataFrame. Read-only, point-in-time.
- `snapshot_dpid_map() -> polars.DataFrame` — reads entire dpid_map into a polars DataFrame.
- `record_scan_start(scan_id: str) -> None` — inserts scan_log row with status `running`.
- `record_scan_end(scan_id: str, status: Literal["success", "failure"], error_msg: str | None = None) -> None` — updates scan_log row with `ended_at` and final status.
- `close() -> None` — closes the connection.

The class should also implement `__enter__` and `__exit__` for context manager usage.

**Testing:**

Tests must verify:
- pyaggregate-unify-qa-qm-sdd.AC2.3: UPSERT idempotence — inserting the same `(dpid, wpid, reqtype)` twice updates `observed_at` but preserves other fields
- pyaggregate-unify-qa-qm-sdd.AC5.1: Surrogate stability — calling `get_or_create_surrogate("aeos")` twice returns the same value
- pyaggregate-unify-qa-qm-sdd.AC5.2: Surrogate auto-extension — calling with a new DPID returns a fresh, never-before-seen surrogate
- Surrogate monotonicity — surrogates are assigned in order (`dp_001`, `dp_002`, ...)
- WAL mode is set (query `PRAGMA journal_mode` after init)
- `snapshot_catalog()` returns a polars DataFrame with expected columns
- `snapshot_dpid_map()` returns a polars DataFrame with expected columns
- Scan log records start and end correctly
- Context manager opens and closes connection

Follow project testing patterns. Use `tmp_path` for database files.

**Verification:**

Run: `pytest tests/test_catalog_store.py -v`

Expected: All tests pass.

**Commit:** `feat: add sqlite catalog store with UPSERT and surrogate mapping`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Test CatalogStore

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.3, pyaggregate-unify-qa-qm-sdd.AC5.1, pyaggregate-unify-qa-qm-sdd.AC5.2

**Files:**
- Create: `tests/test_catalog_store.py`

**Testing:**

Tests must cover:
- `init_schema` creates all three tables (verify via `sqlite_master`)
- `upsert_catalog_row` insert then update: second call with different `verid` updates the row
- `upsert_catalog_row` idempotence: same values twice, only `observed_at` changes
- `get_or_create_surrogate` first call creates `dp_001`
- `get_or_create_surrogate` second different DPID creates `dp_002`
- `get_or_create_surrogate` same DPID returns same surrogate (stability)
- `snapshot_catalog` returns polars DataFrame with correct schema
- `snapshot_dpid_map` returns polars DataFrame with correct schema
- WAL mode: after init, `PRAGMA journal_mode` returns `wal`
- Concurrent read during write: open two connections to same db, start a write transaction in one, verify the other can still read (WAL allows this)
- Scan log: `record_scan_start` + `record_scan_end` produce correct row

**Verification:**

Run: `pytest tests/test_catalog_store.py -v`

Expected: All tests pass.

**Commit:** `test: add catalog store tests`

<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->

<!-- START_TASK_3 -->
### Task 3: Wire init-db, show-catalog, show-dpid-map, show-scans CLI commands

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC1.2

**Files:**
- Modify: `src/pyaggregate/cli.py`

**Implementation:**

Replace the stub implementations for `init-db`, `show-catalog`, `show-dpid-map`, and `show-scans` with real implementations:

- `init-db`: Resolve config, create `CatalogStore`, call `init_schema()`, print success message.
- `show-catalog`: Resolve config, open `CatalogStore`, call `snapshot_catalog()`, print the DataFrame (use `print(df)` for polars' built-in table rendering).
- `show-dpid-map`: Same pattern, call `snapshot_dpid_map()`.
- `show-scans`: Query scan_log table and print results.

Add `--catalog` option to `show-catalog`, `show-dpid-map`, and `show-scans` commands to allow pointing at an alternate database (supports AC4.1 in later phases).

**Testing:**

No new test file — wiring is verified operationally and in Phase 8 e2e test.

**Verification:**

Run: `pyaggregate init-db --help`

Expected: Shows help for init-db command.

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No lint or format errors.

**Commit:** `feat: wire catalog inspection commands into CLI`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Verify all Phase 3 tests pass

**Files:** None (verification only)

**Verification:**

Run: `pytest tests/test_catalog_store.py tests/test_paths.py tests/test_config.py -v`

Expected: All tests pass.

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No lint or format errors.

**Commit:** No commit needed — verification step.

<!-- END_TASK_4 -->

<!-- END_SUBCOMPONENT_B -->
