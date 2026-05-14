# pyAggregate: Unify QA, QM, and SCDM Aggregation Design
 
## Summary
 
`pyaggregate` is a new Python package that replaces two legacy SAS programs -- the QA Aggregation and SCDM Snapshot Aggregation batch jobs -- plus an ad-hoc CSV-building cron script, unifying them into a single, installable CLI. The core insight driving the design is that all three aggregation types (`qa`, `qm`, `sdd`) share the same underlying data -- approved msoc submissions from data partners -- and differ only in which catalog rows they draw from and which subdirectory they glob. A shared sqlite catalog, populated by a lightweight scanner, makes that distinction trivial.
 
The operational model is deliberately minimal: no daemon, no event loop, no service manager. Two cron jobs -- a 15-minute scanner guarded by `flock`, and a weekly aggregator -- cover the full lifecycle on NFS-mounted directories where inotify is not viable. The architecture enforces a functional-core / imperative-shell split so that pipeline logic (`mask`, `rollup`) is pure and property-testable with `hypothesis`, while all filesystem and sqlite side effects are isolated in scanner, writer, and store modules. Parquet outputs land in hive-style dated run directories with a stable `latest` symlink that Power BI can point at without reconfiguration between runs.
 
## Definition of Done
 
The project is complete when all of the following are true:
 
1. A `pyaggregate` python package installs via `pip install -e .` on python 3.11+ with no `uv` dependency. Lean dependency set: `polars-runtime-64`, `polars-readstat`, `typer` (runtime); `pytest`, `hypothesis`, `ruff`, `pre-commit` (dev). The package uses a `src/` layout per the python programming standards.
2. `pyaggregate scan` walks the configured `requests/{qa,qm}/<dpid>/packages/` tree, identifies the latest approved msoc per `(dpid, wpid, reqtype)`, and upserts a sqlite catalog idempotently. Running it back-to-back produces no spurious changes.
3. `pyaggregate run` (no args) produces three aggregations -- `qa`, `qm`, `sdd` -- each emitting per-table `stacked.parquet`, `masked.parquet`, and `rollup.parquet` (skipping configured `*_stats` patterns in rollup only) into `outputs/<agg>/<YYYY-MM-DD>/...`, and updates the `outputs/<agg>/latest` symlink to point at the new run directory.
4. `pyaggregate run --type <agg>` runs a single aggregation type as an escape hatch; `--catalog`, `--output-root`, `--run-id`, and `--no-update-latest` flags exist for adhoc / backfill use.
5. DPID surrogate IDs are stable across runs via a sqlite `dpid_map` table that auto-extends for newly-observed DPs. A `dpid_map.csv` sidecar is written into each run directory describing the surrogate mapping used for that run's `masked/` outputs.
6. The SDD (SCDM Snapshot) aggregation stacks `msoc/scdm_snapshot/` subtrees from BOTH `qar` and `qmr` packages per DP, treating their file sets as complementary (no overlap, no tiebreaker required at the file-name level).
7. The system runs operationally via crontab -- `pyaggregate scan` every 15 minutes guarded by `flock`, `pyaggregate run` weekly. The legacy SAS-based QA Aggregation and SCDM Snapshot Aggregation programs can be retired.
8. Tests cover: pure pipeline functions (mask, rollup) via `hypothesis` property tests; scanner behaviour via integration tests using `tmp_path` directory-tree fixtures; an end-to-end smoke test using synthetic `.sas7bdat` fixtures verifying scan -> catalog -> run -> outputs end-to-end.
 
## Acceptance Criteria
 
### pyaggregate-unify-qa-qm-sdd.AC1: Package installs and CLI is reachable
 
- **AC1.1 Success:** `pip install -e .` succeeds on python 3.11.x, 3.12.x, and 3.13.x with no `uv`-related errors.
- **AC1.2 Success:** `pyaggregate --help` exits 0 and lists subcommands `scan`, `run`, `init-db`, `show-catalog`, `show-dpid-map`, `show-scans`.
- **AC1.3 Failure:** `pip install -e .` on python 3.10 surfaces a clear "requires python >=3.11" error from pip metadata, not a runtime traceback.
 
### pyaggregate-unify-qa-qm-sdd.AC2: Scanner correctly maintains the catalog
 
- **AC2.1 Success:** Given a tree where `aeos` has `soc_qar_wp041_aeos_v01/msoc/` AND `soc_qar_wp041_aeos_v02/msoc/`, the catalog row for `(aeos, wp041, qar)` references `v02`'s msoc path.
- **AC2.2 Success:** Given a tree where `aeos/soc_qar_wp041_aeos_v01/` contains only `msoc_new/` (failed QA), the scanner does NOT create a catalog row for `(aeos, wp041, qar)`.
- **AC2.3 Success:** Running `pyaggregate scan` twice in succession against an unchanged tree produces zero net catalog changes (verified via `observed_at` being the only changed field, or by comparing snapshots).
- **AC2.4 Success:** `has_scdm = 1` is set on rows whose `msoc/scdm_snapshot/` exists, `0` otherwise.
- **AC2.5 Failure:** A package directory with an unparseable name (e.g., `soc_qar_wp041_aeos/` missing the verid suffix) is logged at WARN and skipped without aborting the scan.
- **AC2.6 Failure:** A second concurrent `pyaggregate scan` invocation while one is already running exits 0 with a "scan already in progress" log message (flock contention is handled, not crashed on).
 
### pyaggregate-unify-qa-qm-sdd.AC3: Aggregation produces the three expected outputs per table
 
- **AC3.1 Success:** For each table in the `qa` config, `outputs/qa/<run_id>/stacked/<table>.parquet` exists and contains rows from every catalog row where `reqtype = 'qar'`.
- **AC3.2 Success:** Stacked output preserves the real `dpid` column with values matching catalog `dpid`s.
- **AC3.3 Success:** `outputs/qa/<run_id>/masked/<table>.parquet` row count equals stacked row count, contains a `surrogate_id` column, and contains NO column named `dpid`.
- **AC3.4 Success:** `outputs/qa/<run_id>/rollup/<table>.parquet` contains no `dpid` and no `surrogate_id` columns; sum over numeric columns equals the corresponding sum in stacked.
- **AC3.5 Success:** Rollup row count is less than or equal to stacked row count (collapses identical key combinations across DPs).
- **AC3.6 Success:** All output files are written via temp-then-rename -- no `.tmp` files survive a successful run.
- **AC3.7 Success:** Adding `--type qa --type sdd` produces only `qa` and `sdd` output trees; `qm` is untouched.
 
### pyaggregate-unify-qa-qm-sdd.AC4: Catalog and run flags support adhoc / backfill use
 
- **AC4.1 Success:** `pyaggregate run --catalog /tmp/alt.db` reads from the alternate catalog and ignores the configured default.
- **AC4.2 Success:** `pyaggregate run --output-root /tmp/out` writes outputs under `/tmp/out` and does not touch the configured `output_root`.
- **AC4.3 Success:** `pyaggregate run --no-update-latest` produces a complete run directory but does NOT modify the existing `outputs/<agg>/latest` symlink.
- **AC4.4 Success:** `pyaggregate run --run-id 2026-05-14-rerun` writes to a directory of that name; combined with `--no-update-latest` allows producing parallel reruns without disturbing prod.
- **AC4.5 Failure:** `pyaggregate run --run-id <existing>` without `--force` exits non-zero with a "run directory already exists" error and writes nothing.
 
### pyaggregate-unify-qa-qm-sdd.AC5: DPID surrogate mapping is stable and auto-extending
 
- **AC5.1 Success:** A DPID seen in a previous run receives the same surrogate_id in subsequent runs (across multiple `run` invocations spanning multiple scans).
- **AC5.2 Success:** A newly-observed DPID receives a fresh surrogate_id never previously assigned, and is added to `dpid_map` automatically.
- **AC5.3 Success:** Each run directory contains a `dpid_map.csv` whose contents exactly correspond to the surrogates present in that run's `masked/` outputs.
 
### pyaggregate-unify-qa-qm-sdd.AC6: SDD aggregation pulls from both qar and qmr packages
 
- **AC6.1 Success:** Given a DP with both `soc_qar_wp041_<dp>_v01/msoc/scdm_snapshot/` and `soc_qmr_wp041_<dp>_v01/msoc/scdm_snapshot/` populated with complementary file sets, the SDD output contains rows derived from BOTH subtrees.
- **AC6.2 Success:** Given a DP where only the qar package's scdm_snapshot exists (qmr not yet returned), SDD includes the qar contribution and does not error on the missing qmr side.
- **AC6.3 Failure:** If a file with the same name appears in BOTH the qar and qmr scdm_snapshot for the same `(dpid, wpid)` (collision rather than complementary), the run logs a WARN naming the conflicting file and includes both rows in stacked output (no silent dedup).
 
### pyaggregate-unify-qa-qm-sdd.AC7: `*_stats` exclusion applies to rollup only
 
- **AC7.1 Success:** Tables matching any pattern in `agg.<type>.exclude_from_rollup` produce `stacked.parquet` and `masked.parquet` but NO `rollup.parquet`.
- **AC7.2 Success:** Non-matching tables in the same agg_type produce all three outputs.
 
### pyaggregate-unify-qa-qm-sdd.AC8: `latest` symlink is always valid
 
- **AC8.1 Success:** After a successful run with `update_latest=True`, `outputs/<agg>/latest` resolves to the just-written `<run_id>` directory.
- **AC8.2 Success:** The symlink update is atomic -- at no observable point during the swap is `outputs/<agg>/latest` missing or pointing at a nonexistent target. (Verified by polling during the writer's symlink-update operation in a test.)
 
### pyaggregate-unify-qa-qm-sdd.AC9: End-to-end smoke test passes
 
- **AC9.1 Success:** Starting from an empty state directory and a synthetic `requests/` tree, the sequence `pyaggregate init-db` -> `pyaggregate scan` -> `pyaggregate run` produces all expected output files for all three agg types with internally consistent row counts.
- **AC9.2 Success:** Re-running `pyaggregate run` with the same `--run-id` and `--force` overwrites the previous outputs cleanly.
 
## Glossary
 
- **DPID**: Data partner identifier -- the string key that identifies one contributing organisation across all submissions (e.g., `aeos`, `cms`).
- **surrogate_id**: An opaque stable identifier (e.g., `dp_001`) substituted for the real DPID in `masked/` outputs to prevent partner re-identification in shared analytical files.
- **msoc / msoc_new**: Submission directories inside a package directory. `msoc/` signals an approved QA submission; `msoc_new/` signals a submission still under review or a failed one. The scanner uses presence of `msoc/` as the approval gate.
- **qar / qmr**: Request types encoding the two lifecycle artifacts per partner workplan. `qar` is the QA submission (quality assurance review); `qmr` is the QM submission (quality monitoring review). Both are physically delivered by data partners.
- **sdd**: The "SCDM Snapshot" aggregation type -- stacks the `msoc/scdm_snapshot/` subtrees from both `qar` and `qmr` packages for each data partner, treating them as complementary file sets.
- **wpid**: Workplan identifier (e.g., `wp041`) -- DP-local; the same `wpid` value for two different DPs refers to unrelated workplans.
- **verid**: Version identifier (e.g., `v01`, `v02`) within a `(dpid, wpid, reqtype)` tuple, incremented only on QA failure and resubmission.
- **request_id**: The full parsed package-directory name structure: `soc_<reqtype>_<wpid>_<dpid>_<verid>`. The scanner's path grammar is defined entirely by this convention.
- **scdm_snapshot**: A subdirectory inside an approved `msoc/` containing SCDM-format SAS dataset files. Its presence (`has_scdm = 1` in the catalog) determines whether a DP contributes to the `sdd` aggregation.
- **polars**: A Rust-backed DataFrame library used here for all in-memory frame manipulation and parquet I/O -- faster and more memory-efficient than pandas for wide concatenation workloads. The 64-bit runtime (`polars-runtime-64`) is required for correct handling of large integer identifiers.
- **polars-readstat**: Polars-native SAS reader built on the ReadStat C library. Provides `scan_readstat` (lazy) and `ScanReadstat` (metadata-only) APIs that handle SAS date/time epoch conversion, string typing, and 64-bit integer overrides without an intermediate pandas conversion. Replaces the older `pyreadstat` library.
- **typer**: CLI framework built on Click that generates typed argument parsers from Python function signatures; used to implement the `pyaggregate` CLI.
- **hypothesis**: Property-based testing library; used to verify pipeline invariants (mask uniqueness, rollup sum preservation) over generated inputs rather than hand-written fixtures.
- **FCIS / functional-core imperative-shell**: Architectural pattern separating pure functions with no side effects (functional core) from modules that perform I/O (imperative shell), enabling the core to be tested without mocking.
- **hive partitioning**: Directory layout convention where each run's outputs land under a date-named subdirectory (`YYYY-MM-DD/`), making it trivial to retain history and roll back by re-pointing a symlink.
- **flock**: POSIX advisory file lock (`fcntl.flock`) used to ensure only one `pyaggregate scan` process runs at a time on the same host.
- **WAL mode**: SQLite Write-Ahead Logging mode; allows concurrent readers to proceed without blocking while a writer commits, necessary here because `show-catalog` inspection commands may run during a scan.
- **NFS / inotify**: NFS is the network filesystem hosting the `requests/` tree. `inotify` is a Linux kernel facility for filesystem change events that does not propagate across NFS clients -- the reason the design uses polling rather than event-driven watching.
- **Power BI**: The downstream BI tool that consumes the parquet outputs via the `outputs/<agg>/latest` symlink; the stable symlink path means Power BI data sources never need reconfiguring between runs.
 
## Architecture
 
`pyaggregate` is a single python package with a `typer` CLI that exposes two cooperating subcommands (`scan` and `run`) plus a handful of read-only inspection commands (`init-db`, `show-catalog`, `show-dpid-map`, `show-scans`). It replaces two SAS programs (QA Aggregation, SCDM Snapshot Aggregation) and the daily bash CSV-building cron job with one unified python implementation.
 
The architecture splits cleanly into two concerns:
 
1. **Catalog maintenance.** A one-shot scanner runs every 15 minutes via cron. It walks `requests/{qa,qm}/<dpid>/packages/soc_<reqtype>_<wpid>/soc_<reqtype>_<wpid>_<dpid>_<verid>/`, finds the highest `verid` whose `msoc/` directory exists (versus `msoc_new/`), and idempotently upserts a sqlite row keyed `(dpid, wpid, reqtype) -> (verid, msoc_path, has_scdm, observed_at)`. The scanner is profile-agnostic -- it knows the path grammar, not the downstream aggregation semantics. It uses `flock` for concurrency safety and is restart-safe by construction (every run rebuilds truth from the filesystem).
 
2. **Aggregation.** A weekly cron-driven `pyaggregate run` reads the catalog as a snapshot, derives per-aggregation-type input paths, and produces three parquet outputs per source table: `stacked` (concat across DPs with real DPID), `masked` (DPID swapped for stable surrogate via sqlite lookup), and `rollup` (drop DPID, group by remaining keys, sum/count). Outputs land in `outputs/<agg>/<YYYY-MM-DD>/<output_type>/<table>.parquet` with an `outputs/<agg>/latest` symlink pointing at the most recent run. A `dpid_map.csv` sidecar inside each run directory documents the surrogate mapping used.
 
The three aggregation types are derived from a single shared catalog:
 
| agg type | source rule |
|---|---|
| `qa`  | `SELECT msoc_path FROM catalog WHERE reqtype = 'qar'`; per row, glob `*.sas7bdat` directly under `msoc/` (excluding `scdm_snapshot/`) |
| `qm`  | `SELECT msoc_path FROM catalog WHERE reqtype = 'qmr'`; per row, glob `*.sas7bdat` directly under `msoc/` (excluding `scdm_snapshot/`) |
| `sdd` | `SELECT msoc_path FROM catalog WHERE has_scdm = 1`; per row, glob `msoc/scdm_snapshot/*.sas7bdat` across BOTH reqtypes (qar and qmr contribute complementary file sets per `(dpid, wpid)`) |
 
**Path grammar.** Catalog rows are populated by parsing the request_id structure: `soc_<reqtype>_<wpid>_<dpid>_<verid>` where `reqtype` is `qar` or `qmr` (the only types data partners physically deliver), `wpid` is `wp<NNN>` and is DP-local (`aeos.wp041` and `cms.wp041` are unrelated workplans), and `verid` resets to `v01` per `(dpid, wpid, reqtype)` and only iterates on QA failure. Per DP, `soc_qar_wp041` and `soc_qmr_wp041` are linked -- they represent the QA and QM lifecycle artifacts for the same logical ETL.
 
**NFS reality.** Watched directories live on NFS mounts. inotify does not propagate events between NFS clients, so the design is poll-based. This is embraced rather than worked around: a 15-minute cron tick and a sub-second scanner walk for ~14 partners is operationally fine. No daemon, no `systemd` (unavailable in this environment), no event-loop machinery -- just cron + flock + sqlite.
 
**Data flow.**
 
```
cron (every 15 min) -- pyaggregate scan
                       \-- walks requests/{qa,qm}/*/packages/soc_*_wp*/soc_*_wp*_*_v*/
                       \-- for each (dpid, wpid, reqtype): pick max(verid) where msoc/ exists
                       \-- UPSERT catalog row; auto-extend dpid_map for new DPs
 
cron (weekly)       -- pyaggregate run            # all three agg types
                       pyaggregate run --type qa  # one agg type only (escape hatch)
                       \-- reads catalog snapshot, emits per agg_type per table:
                           outputs/<agg>/YYYY-MM-DD/stacked/<table>.parquet
                           outputs/<agg>/YYYY-MM-DD/masked/<table>.parquet
                           outputs/<agg>/YYYY-MM-DD/rollup/<table>.parquet  (unless table matches *_stats)
                           outputs/<agg>/YYYY-MM-DD/dpid_map.csv
                       \-- ln -sfn YYYY-MM-DD outputs/<agg>/latest
```
 
**Project structure.**

```
pyAggregate/
├── src/
│   └── pyaggregate/
│       ├── __init__.py
│       ├── cli.py                 # pattern: Imperative Shell — typer entry point
│       ├── config.py              # pattern: Functional Core — TOML → frozen dataclasses
│       ├── log_config.py          # pattern: Imperative Shell — JSON-lines logger setup
│       ├── core/                  # Functional Core (pure transforms, no I/O)
│       │   ├── paths.py           # RequestId parsing and version ranking
│       │   ├── dpid_mask.py       # surrogate ID substitution
│       │   └── pipeline.py        # stack, mask, rollup orchestration
│       └── io/                    # Imperative Shell (readers, writers, stores)
│           ├── sas_reader.py      # polars-readstat scan_readstat wrapper
│           ├── catalog_store.py   # sqlite catalog + dpid_map + scan_log
│           ├── scanner.py         # filesystem walker → catalog upsert
│           └── writer.py          # parquet + symlink output writer
├── tests/
│   ├── conftest.py
│   ├── test_paths.py
│   ├── test_config.py
│   ├── test_catalog_store.py
│   ├── test_scanner.py
│   ├── test_dpid_mask.py
│   ├── test_pipeline_stacked.py
│   ├── test_pipeline_rollup.py
│   ├── test_input_resolution.py
│   ├── test_stats_exclusion.py
│   ├── test_writer.py
│   ├── test_run_orchestration.py
│   └── test_e2e_smoke.py
├── examples/
│   └── pyaggregate.toml
├── docs/
│   ├── operations.md
│   └── migration.md
├── pyproject.toml
├── .pre-commit-config.yaml
├── .gitignore
└── README.md
```

## Existing Patterns
 
This is a greenfield project -- `pyAggregate/` is empty. Codebase investigation found no existing python source to follow patterns from.
 
The design adopts conventions from the python programming standards and the sibling `scdm_parquet_tide` project:
 
- **`src/` layout with `pyproject.toml` only.** Follows the python programming standards: package lives under `src/`, `pyproject.toml` is the single build/dependency manifest (no `setup.py`, no `requirements.txt`).
- **`polars-readstat` for SAS reading.** Follows the `scdm_parquet_tide` project pattern: uses `scan_readstat` (lazy) and `ScanReadstat` (metadata-only) for 64-bit-aware SAS file reading without pandas intermediation. Uses `polars-runtime-64` for correct large-integer handling.
- **Parquet output, polars-first processing.** Aligns with `scdm_parquet_tide`, which establishes parquet as the analytical interchange format in this organisation.
- **Hive-style date directories with a `latest` symlink.** Standard pattern for serving Power BI dashboards a stable "current" path while preserving historical runs as first-class data.
- **sqlite for operational state.** A pragmatic choice for single-host, single-writer state -- no server to operate, atomic transactions, queryable via stdlib `sqlite3` for adhoc inspection.
- **Functional-core / imperative-shell with `# pattern:` labels.** Per the programming standards, every source file with runtime behaviour gets a `# pattern: Functional Core` or `# pattern: Imperative Shell` comment on line 1. Pipeline logic (`mask`, `rollup`, `paths`) is pure and property-testable in `core/`; scanner, writer, and catalog store carry the side effects in `io/`.
- **`ruff` for linting and formatting.** Single tool replacing `black`, `isort`, `flake8` per the programming standards. Configured in `pyproject.toml`.
- **All function signatures typed.** Per the programming standards: all parameters and return types annotated, `str | None` syntax (not `Optional`), `Literal` for constrained values, frozen dataclasses for structured return types.
 
No existing python codebase patterns were available to follow or diverge from. The design follows the python programming standards and adopts patterns from `scdm_parquet_tide` where applicable.
 
## Implementation Phases
 
<!-- START_PHASE_1 -->
### Phase 1: Project scaffolding
 
**Goal:** Stand up the python package, dependency manifest, and CLI skeleton on the target python version.
 
**Components:**
 
- `pyproject.toml` declaring package metadata, `src/` layout, entry point `pyaggregate = "pyaggregate.cli:app"`, python `>=3.11`, runtime deps (`polars-runtime-64`, `polars-readstat`, `typer`), dev deps (`pytest`, `hypothesis`, `ruff`, `pre-commit`), ruff config (`target-version = "py311"`, `line-length = 100`, rule selections per programming standards), and pytest config. No `requirements.txt` — `pyproject.toml` is the single source of truth for dependencies. See `scdm_parquet_tide/pyproject.toml` for the reference layout.
- `src/pyaggregate/__init__.py`, `src/pyaggregate/cli.py` with empty `typer.Typer()` app and stub commands (`scan`, `run`, `init-db`, `show-catalog`, `show-dpid-map`, `show-scans`)
- `tests/` directory and basic `conftest.py`
- `README.md` with install + invocation instructions
 
**Dependencies:** None (first phase)
 
- `.gitignore` and `.pre-commit-config.yaml` with ruff hooks
 
**Done when:** `pip install -e .` succeeds on python 3.11, 3.12, and 3.13, `pyaggregate --help` lists all stub subcommands, `pytest` runs (zero tests, zero failures), `ruff check` and `ruff format --check` pass.
<!-- END_PHASE_1 -->
 
<!-- START_PHASE_2 -->
### Phase 2: Path grammar and config loader
 
**Goal:** Parse the `soc_<reqtype>_<wpid>_<dpid>_<verid>` request_id grammar and load per-aggregation-type config from TOML.
 
**Components:**
 
- `src/pyaggregate/core/paths.py` (`# pattern: Functional Core`) -- pure functions to parse package directory names into a typed `RequestId` dataclass (reqtype, wpid, dpid, verid), validate them, and rank versions
- `src/pyaggregate/config.py` (`# pattern: Functional Core`) -- loads `pyaggregate.toml` into frozen `AppConfig` and `AggTypeConfig` dataclasses using stdlib `tomllib`. Supports per-table override blocks (`[agg.qa.tables.ae]`) for `rollup_keys` / `rollup_aggs` / `exclude_from_rollup`. Resolves config file location via `--config` CLI flag -> `PYAGGREGATE_CONFIG` env var -> `./pyaggregate.toml` default
- `tests/test_paths.py` -- covers valid grammar, malformed names, version ordering edge cases (v01 vs v10 lexicographic vs numeric)
- `tests/test_config.py` -- covers config loading, missing required fields, per-table overrides, env var precedence
- A sample `pyaggregate.toml` checked in under `examples/` showing all three agg type configurations including `*_stats` exclusion
 
**Dependencies:** Phase 1
 
**Done when:** Tests pass for `pyaggregate-unify-qa-qm-sdd.AC1.1`, `AC1.2`, `AC2.1`. Path parser correctly identifies and orders versions; config loader rejects malformed configs with clear errors.
<!-- END_PHASE_2 -->
 
<!-- START_PHASE_3 -->
### Phase 3: Sqlite catalog store
 
**Goal:** Implement the catalog and dpid_map sqlite schema and the read/write API used by both scanner and aggregator.
 
**Components:**
 
- `src/pyaggregate/io/catalog_store.py` (`# pattern: Imperative Shell`) -- `CatalogStore` class wrapping a sqlite connection (WAL mode), exposing:
  - `init_schema()` -- creates `catalog`, `dpid_map`, `scan_log` tables
  - `upsert_catalog_row(...)` -- atomic INSERT ... ON CONFLICT for `(dpid, wpid, reqtype)`
  - `get_or_create_surrogate(dpid) -> str` -- auto-extends `dpid_map` for new DPs
  - `snapshot_catalog() -> polars.DataFrame` -- read-only point-in-time view
  - `snapshot_dpid_map() -> polars.DataFrame`
  - `record_scan(...)` -- appends a row to `scan_log` with start/end/status
- `src/pyaggregate/cli.py` (`# pattern: Imperative Shell`) wires `pyaggregate init-db` to call `init_schema()`, `show-catalog`, `show-dpid-map`, `show-scans` to call the corresponding snapshot methods and pretty-print
- Schema migration is deliberately out of scope -- `init-db` is one-shot
- `tests/test_catalog_store.py` -- covers UPSERT idempotence, surrogate auto-extension monotonicity, WAL concurrent-read-during-write, snapshot isolation
 
**Schema (informational, defined in `init_schema()`):**
 
```sql
CREATE TABLE catalog (
  dpid        TEXT NOT NULL,
  wpid        TEXT NOT NULL,
  reqtype     TEXT NOT NULL,           -- 'qar' | 'qmr'
  verid       TEXT NOT NULL,
  msoc_path   TEXT NOT NULL,
  has_scdm    INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (dpid, wpid, reqtype)
);
CREATE TABLE dpid_map (
  dpid          TEXT PRIMARY KEY,
  surrogate_id  TEXT NOT NULL UNIQUE,  -- e.g. 'dp_001'
  first_seen_at TEXT NOT NULL
);
CREATE TABLE scan_log (
  scan_id     TEXT PRIMARY KEY,        -- UUID
  started_at  TEXT NOT NULL,
  ended_at    TEXT,
  status      TEXT NOT NULL,           -- 'running' | 'success' | 'failure'
  error_msg   TEXT
);
```
 
**Dependencies:** Phase 1, Phase 2
 
**Done when:** Tests pass for `pyaggregate-unify-qa-qm-sdd.AC2.2`, `AC2.3`, `AC4.1`, `AC4.2`. `pyaggregate init-db` creates a working catalog file. Concurrent reader during writer does not deadlock or block.
<!-- END_PHASE_3 -->
 
<!-- START_PHASE_4 -->
### Phase 4: Scanner implementation
 
**Goal:** Walk the requests tree, populate the catalog with the latest approved msoc per `(dpid, wpid, reqtype)`.
 
**Components:**
 
- `src/pyaggregate/io/scanner.py` (`# pattern: Imperative Shell`) -- `run_scan(config, store)` function that:
  - Walks both `requests/qa/*/packages/soc_qar_wp*/` and `requests/qm/*/packages/soc_qmr_wp*/`
  - For each package directory, lists version subdirectories, sorts by parsed `verid` descending
  - Picks the highest version whose `msoc/` exists (skips ones with only `msoc_new/`)
  - Detects whether `msoc/scdm_snapshot/` exists, sets `has_scdm` accordingly
  - UPSERTs the row, logs malformed packages and continues
  - Records start/end/status in `scan_log` with a UUID
- CLI wiring: `pyaggregate scan` calls `run_scan`. `pyaggregate scan --dry-run` runs walk + diff against current catalog and logs intended changes without writing.
- Lockfile guard: `pyaggregate scan` acquires an `fcntl.flock` on `<catalog_db>.scan.lock` (path derived from config) and exits cleanly if another scan holds it
- `tests/test_scanner.py` -- uses `tmp_path` to construct realistic directory trees (passed packages, failed packages with only `msoc_new`, mixed versions, missing `scdm_snapshot`, malformed package names) and asserts catalog state after scan; idempotence verified by running twice
- `tests/test_scanner_concurrency.py` -- verifies that two simultaneous `scan` invocations do not corrupt state (one acquires lock, other exits)
 
**Dependencies:** Phase 2, Phase 3
 
**Done when:** Tests pass for `pyaggregate-unify-qa-qm-sdd.AC2.1`, `AC2.2`, `AC2.3`, `AC2.4`, `AC2.5`. Scanner correctly identifies latest approved version, handles malformed packages without aborting, runs idempotently, and is concurrency-safe via flock.
<!-- END_PHASE_4 -->
 
<!-- START_PHASE_5 -->
### Phase 5: Aggregation pipeline (stacked + masked)
 
**Goal:** Read sas7bdat inputs per agg_type per table, produce `stacked.parquet` and `masked.parquet` outputs.
 
**Components:**
 
- `src/pyaggregate/io/sas_reader.py` (`# pattern: Imperative Shell`) -- `read_table(msoc_path, table_name, dpid) -> polars.LazyFrame`. Uses `polars_readstat.scan_readstat` to lazily scan `.sas7bdat` files (handles SAS date/time epoch conversion, string typing, and 64-bit integer overrides natively — no intermediate pandas conversion). Injects `dpid` column. Uses `ScanReadstat` for metadata-only schema validation against config; logs and quarantines mismatches.
- `src/pyaggregate/core/dpid_mask.py` (`# pattern: Functional Core`) -- `mask_dpid(frame, dpid_map_frame) -> polars.DataFrame`. Pure function: left-join on `dpid`, swap with `surrogate_id`, drop original `dpid` column. The map is passed in (not fetched here) to keep this pure.
- `src/pyaggregate/core/pipeline.py` (`# pattern: Functional Core`) -- `aggregate_table(agg_type_config, msoc_paths_with_dpid, table_name, dpid_map) -> {output_type: polars.DataFrame}`. Orchestrates read -> stack -> mask. Returns a dict mapping `'stacked'`, `'masked'` (and `'rollup'`, added in Phase 6) to frames.
- Per-agg-type input resolution helper that takes a catalog snapshot and yields `(dpid, msoc_path)` tuples per table for `qa` (qar reqtype, exclude scdm_snapshot/), `qm` (qmr reqtype, exclude scdm_snapshot/), and `sdd` (any reqtype where has_scdm=1, source the scdm_snapshot/ subtree)
- `tests/test_dpid_mask.py` -- `hypothesis` property tests asserting: every input DPID maps to exactly one surrogate; surrogate set is unique; no real DPID survives in masked output; row count preserved
- `tests/test_pipeline_stacked.py` -- fixture-based test using synthetic `.sas7bdat` files; asserts that stacking 3 partners produces 3x row count and each row carries the correct dpid
- `tests/test_input_resolution.py` -- given a catalog snapshot, asserts `qa` resolves only qar rows, `qm` only qmr, and `sdd` resolves both reqtypes' scdm_snapshot subtrees
 
**Dependencies:** Phase 2, Phase 3
 
**Done when:** Tests pass for `pyaggregate-unify-qa-qm-sdd.AC3.1`, `AC3.2`, `AC3.3`, `AC5.1`, `AC5.2`, `AC6.1`, `AC6.2`. Stacked frames contain real DPIDs; masked frames contain surrogates only; SDD pulls from both reqtypes' scdm_snapshot subtrees.
<!-- END_PHASE_5 -->
 
<!-- START_PHASE_6 -->
### Phase 6: Rollup and `_stats` exclusion
 
**Goal:** Add the third output (rollup) and enforce per-table rollup-exclusion patterns.
 
**Components:**
 
- `src/pyaggregate/core/pipeline.py` -- extend `aggregate_table` to also produce a `'rollup'` frame: drop `dpid`, group by `rollup_keys` (per-table from config; sensible default = all non-numeric cols), apply `rollup_aggs` (per-table from config; default = sum of numeric cols)
- Rollup-exclusion logic: skip rollup output entirely for tables matching any glob in `agg_type_config.exclude_from_rollup` (e.g., `*_stats`). Stacked and masked outputs are still produced for excluded tables.
- `tests/test_pipeline_rollup.py` -- `hypothesis` property tests: for any synthetic frame, rollup row count <= stacked row count; sum of rollup numeric columns equals sum of stacked numeric columns; rollup contains no `dpid` column
- `tests/test_stats_exclusion.py` -- given a config with `exclude_from_rollup = ["*_stats"]`, assert that `ae_stats` table produces stacked + masked but no rollup output, and `ae` (non-stats) produces all three
 
**Dependencies:** Phase 5
 
**Done when:** Tests pass for `pyaggregate-unify-qa-qm-sdd.AC3.4`, `AC3.5`, `AC7.1`, `AC7.2`. Rollup output omits DPID and aggregates correctly; `*_stats` tables skip rollup but still emit stacked and masked.
<!-- END_PHASE_6 -->
 
<!-- START_PHASE_7 -->
### Phase 7: Writer, run orchestration, and `latest` symlink
 
**Goal:** Wire pipeline outputs to disk in the agreed layout, manage the `latest` symlink, write the dpid_map sidecar, and orchestrate per-run execution end-to-end.
 
**Components:**
 
- `src/pyaggregate/io/writer.py` (`# pattern: Imperative Shell`) -- `write_run(output_root, agg_type, run_id, table_outputs, dpid_map_frame, update_latest)`:
  - Writes each frame to `outputs/<agg_type>/<run_id>/<output_type>/<table>.parquet` via `polars.write_parquet`
  - Writes `dpid_map.csv` to `outputs/<agg_type>/<run_id>/dpid_map.csv`
  - All writes go to `<path>.tmp` then `os.rename` for atomicity
  - When `update_latest=True`, atomically updates `outputs/<agg_type>/latest` symlink via `os.symlink` to a temp name then `os.rename` (POSIX rename is atomic for symlinks too)
- `src/pyaggregate/cli.py` -- implement `run` subcommand:
  - Default: runs all three agg types from the configured catalog
  - `--type <agg>` (repeatable): subset of agg types
  - `--catalog <path>` / `--output-root <path>` / `--run-id <id>` / `--no-update-latest` for adhoc use
  - Default `run-id` is today's date in `YYYY-MM-DD`
  - Refuses to overwrite an existing `<run_id>` directory unless `--force` is passed
- `tests/test_writer.py` -- verify file layout, atomic temp-then-rename behaviour, symlink update is atomic (no observable window where `latest` is missing)
- `tests/test_run_orchestration.py` -- end-to-end-ish: synthetic catalog -> run -> assert all expected output files exist with correct content
 
**Dependencies:** Phase 5, Phase 6
 
**Done when:** Tests pass for `pyaggregate-unify-qa-qm-sdd.AC3.6`, `AC3.7`, `AC4.3`, `AC4.4`, `AC8.1`, `AC8.2`. `pyaggregate run` writes the expected file tree; `latest` symlink updates atomically; adhoc flags allow redirecting catalog/output without disturbing prod state.
<!-- END_PHASE_7 -->
 
<!-- START_PHASE_8 -->
### Phase 8: End-to-end smoke test, logging, and operational documentation
 
**Goal:** Prove the whole system works end-to-end on synthetic data, finalize structured logging, and document the operational model so the SAS programs can be retired.
 
**Components:**
 
- `tests/test_e2e_smoke.py` -- full pipeline test:
  - Constructs a `tmp_path` `requests/` tree with 3 synthetic DPs across qa and qm, including approved + unapproved + scdm_snapshot directories
  - Constructs a `pyaggregate.toml` pointing at it
  - Runs `pyaggregate init-db`, `pyaggregate scan`, `pyaggregate run` via `subprocess` (real CLI invocation)
  - Asserts: all expected output files exist; `latest` symlinks resolve correctly; stacked/masked/rollup row counts are consistent; `dpid_map.csv` matches the surrogates used in `masked/` outputs
- `src/pyaggregate/log_config.py` (`# pattern: Imperative Shell`) -- structured JSON-lines logger writing to `<state_dir>/logs/pyaggregate-YYYY-MM-DD.log` (rotated daily) plus stderr, configured once at the CLI entry point per the programming standards. Uses relative paths in `source_path` fields — never absolute paths. Each `scan` and `run` invocation gets a UUID; key events (scan start/end, per-table read/row-count, validation outcomes, errors) emit one JSON record each. Core modules use `logging.getLogger(__name__)` and nothing else.
- `docs/operations.md` -- operator-facing doc covering:
  - Cron entries (`*/15 * * * * flock -n /var/run/pyaggregate-scan.lock pyaggregate scan` and `0 3 * * 0 pyaggregate run`)
  - State directory layout (`catalog.db`, logs, lockfile)
  - Backup procedure (nightly `cp catalog.db`)
  - Rollback procedure (`ln -sfn <previous-date> outputs/<agg>/latest`)
  - SAS program retirement checklist: parity verification on a known week's data before cutover
- `docs/migration.md` -- one-time parity verification process: run pyaggregate against the same week's input as a recent SAS run, diff outputs, reconcile any discrepancies before retirement
 
**Dependencies:** Phase 7
 
**Done when:** Tests pass for `pyaggregate-unify-qa-qm-sdd.AC9.1`, `AC9.2`. End-to-end smoke test passes on a fresh checkout. Operator doc reviewed by an operator. Parity verification documented (execution of the parity check itself happens at deployment time, not as part of phase completion).
<!-- END_PHASE_8 -->
 
## Additional Considerations
 
**Error handling.** A single malformed package directory must never abort a scan -- it logs and skips. A single corrupted `.sas7bdat` file during a run logs, skips that table for that DP, and proceeds; the run completes with a non-zero exit code if any tables were skipped, so cron's mailto surfaces the issue. Catastrophic failure (config missing, sqlite locked, disk full) aborts cleanly with a stack trace.
 
**Schema drift.** The expected per-table schema is declared in config. Read-time validation logs deviations (column added, column removed, type changed) but does NOT abort -- the row is included with `null` for missing columns and a warning is logged. This trades strictness for resilience; the alternative (abort on first drift) would block the entire weekly run on a single partner's harmless schema tweak.
 
**NFS directory caching.** A freshly-promoted `msoc/` directory may not appear in a scan immediately due to NFS client-side caching. The 15-minute scan cadence absorbs this -- the next tick catches it. Worst-case latency from approval to catalog visibility is 15-30 minutes, acceptable given the weekly aggregation cadence.
 
**No event-driven mode.** The original ask was "inotify or async inotify". After investigation, inotify cannot observe NFS changes from other clients and is incompatible with this deployment. The polling-via-cron design is the operational reality, not a fallback. If the deployment ever moves off NFS, switching to `watchfiles` would be a localized change to `scanner.py`.
 
**Future extensibility.** Adding a fourth aggregation type (e.g., a new request_type the partners start delivering) requires: a new `[agg.<name>]` config block declaring its source rule and tables, no code changes if the rule fits the existing pattern (filter catalog rows + glob inside msoc). A genuinely novel source rule (e.g., aggregating across sub-subdirectories) requires a new branch in the input-resolution helper.
 
**Out of scope.** Schema migration in sqlite (treat as one-shot init); supporting non-NFS storage backends (deployment is NFS-only); a daemon mode (no `systemd` available); UV / Poetry packaging (pip-only environment); `requirements.txt` generation (all dependency metadata lives in `pyproject.toml`); UI / dashboard (Power BI consumes the parquet outputs directly).
