# pyAggregate — Phase 2: Path grammar and config loader

**Goal:** Parse the `soc_<reqtype>_<wpid>_<dpid>_<verid>` request_id grammar and load per-aggregation-type config from TOML.

**Architecture:** Both modules are Functional Core — pure functions and frozen dataclasses, no I/O.

**Tech Stack:** Python 3.11+ stdlib (`tomllib`, `dataclasses`, `re`, `pathlib`)

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield, Phase 1 creates scaffold. Phase 2 creates `core/paths.py` and `config.py`.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pyaggregate-unify-qa-qm-sdd.AC1: Package installs and CLI is reachable
- **pyaggregate-unify-qa-qm-sdd.AC1.1 Success:** `pip install -e .` succeeds on python 3.11.x, 3.12.x, and 3.13.x with no `uv`-related errors.
- **pyaggregate-unify-qa-qm-sdd.AC1.2 Success:** `pyaggregate --help` exits 0 and lists subcommands `scan`, `run`, `init-db`, `show-catalog`, `show-dpid-map`, `show-scans`.

### pyaggregate-unify-qa-qm-sdd.AC2: Scanner correctly maintains the catalog
- **pyaggregate-unify-qa-qm-sdd.AC2.1 Success:** Given a tree where `aeos` has `soc_qar_wp041_aeos_v01/msoc/` AND `soc_qar_wp041_aeos_v02/msoc/`, the catalog row for `(aeos, wp041, qar)` references `v02`'s msoc path.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Implement RequestId parser in core/paths.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.1 (path parsing and version ordering)

**Files:**
- Create: `src/pyaggregate/core/paths.py`

**Implementation:**

Create `src/pyaggregate/core/paths.py` with `# pattern: Functional Core` on line 1.

Implement:
- A frozen dataclass `RequestId` with fields: `reqtype: Literal["qar", "qmr"]`, `wpid: str`, `dpid: str`, `verid: str`, `raw: str` (the original directory name).
- A function `parse_request_id(dirname: str) -> RequestId | None` that parses package directory names matching the pattern `soc_<reqtype>_<wpid>_<dpid>_<verid>`. Returns `None` for malformed names. Use a compiled regex.
  - `reqtype` must be `qar` or `qmr`
  - `wpid` must match `wp\d+` (e.g., `wp041`)
  - `verid` must match `v\d+` (e.g., `v01`, `v02`)
  - `dpid` is the remainder between wpid and verid segments
- A function `verid_sort_key(verid: str) -> int` that extracts the numeric portion for correct ordering (`v02` > `v01`, `v10` > `v9`). This is critical — lexicographic sort would order `v10` before `v2`.
- A function `pick_latest_approved(entries: list[tuple[RequestId, bool]]) -> RequestId | None` that takes a list of `(RequestId, has_msoc)` tuples for the same `(dpid, wpid, reqtype)`, filters to only those where `has_msoc is True` (the `msoc/` directory must exist — `msoc_new/` means unapproved), sorts by `verid_sort_key` descending, and returns the highest version's `RequestId`. Returns `None` if no approved version exists. The caller (scanner, in Phase 4) is responsible for checking `msoc/` existence and passing the boolean — this keeps `core/paths.py` genuinely pure and testable without `tmp_path`.

**Testing (implemented in Task 2):**

The following behaviours must be tested — Task 2 creates the test file with detailed cases:
- `parse_request_id` correctly parses valid names like `soc_qar_wp041_aeos_v01` into `RequestId(reqtype="qar", wpid="wp041", dpid="aeos", verid="v01")`
- `parse_request_id` returns `None` for malformed names (missing verid, bad reqtype, etc.)
- `verid_sort_key` orders versions numerically: `v01 < v02 < v10` (not lexicographic)
- `pick_latest_approved` selects highest version where `has_msoc=True` (pure — no filesystem access)

**Verification:**

Run: `pytest tests/test_paths.py -v`

Expected: All tests pass.

**Commit:** `feat: add RequestId parser and version ranking`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Test RequestId parser

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC2.1

**Files:**
- Create: `tests/test_paths.py`

**Testing:**

Tests must verify each of these scenarios:
- pyaggregate-unify-qa-qm-sdd.AC2.1: Given `soc_qar_wp041_aeos_v01` and `soc_qar_wp041_aeos_v02`, version ranking picks `v02`
- Valid parse: `soc_qar_wp041_aeos_v01` → `RequestId(reqtype="qar", wpid="wp041", dpid="aeos", verid="v01")`
- Valid parse: `soc_qmr_wp041_cms_v03` → `RequestId(reqtype="qmr", wpid="wp041", dpid="cms", verid="v03")`
- Malformed: `soc_qar_wp041_aeos` (missing verid) → `None`
- Malformed: `soc_xyz_wp041_aeos_v01` (bad reqtype) → `None`
- Malformed: `totally_wrong` → `None`
- Malformed: empty string → `None`
- Version ordering: `verid_sort_key("v10") > verid_sort_key("v02") > verid_sort_key("v01")`
- `pick_latest_approved` with mixed approved/unapproved versions: `[(rid_v01, True), (rid_v02, False)]` → returns `rid_v01` (highest with `has_msoc=True`)
- `pick_latest_approved` with no approved versions: all `has_msoc=False` → returns `None`
- `pick_latest_approved` is pure: no `tmp_path` needed, just pass booleans

**Verification:**

Run: `pytest tests/test_paths.py -v`

Expected: All tests pass.

**Commit:** `test: add RequestId parser tests`

<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-5) -->

<!-- START_TASK_3 -->
### Task 3: Implement config loader in config.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC1.1, pyaggregate-unify-qa-qm-sdd.AC1.2

**Files:**
- Create: `src/pyaggregate/config.py`

**Implementation:**

Create `src/pyaggregate/config.py` with `# pattern: Functional Core` on line 1.

Implement:
- Frozen dataclass `AggTypeConfig` with fields:
  - `name: str` — aggregation type name (`qa`, `qm`, `sdd`)
  - `source_reqtype: str | None` — for `qa` and `qm`, the reqtype to filter on
  - `source_field: str | None` — for `sdd`, the catalog field to filter on (e.g., `has_scdm`)
  - `subdirectory: str | None` — for `sdd`, the subdirectory under `msoc/` to glob
  - `exclude_from_rollup: tuple[str, ...]` — glob patterns for tables to exclude from rollup output
  - `table_overrides: types.MappingProxyType[str, TableOverride]` — per-table config overrides (immutable mapping to preserve frozen dataclass invariant; construct via `types.MappingProxyType(dict_value)` in `load_config`)
- Frozen dataclass `TableOverride` with optional fields:
  - `rollup_keys: tuple[str, ...] | None`
  - `rollup_aggs: dict[str, str] | None`
- Frozen dataclass `ScanConfig` with fields:
  - `requests_root: Path`
- Frozen dataclass `StateConfig` with fields:
  - `catalog_db: Path`
  - `log_dir: Path`
- Frozen dataclass `OutputConfig` with fields:
  - `output_root: Path`
- Frozen dataclass `AppConfig` with fields:
  - `scan: ScanConfig`
  - `state: StateConfig`
  - `output: OutputConfig`
  - `agg_types: dict[str, AggTypeConfig]`
- A function `load_config(path: Path) -> AppConfig` that reads a TOML file via `tomllib`, validates required fields, and returns a frozen `AppConfig`. Raises `ValueError` with a clear message for missing required fields.
- A function `resolve_config_path(cli_path: Path | None) -> Path` that resolves config file location via: `--config` CLI flag → `PYAGGREGATE_CONFIG` env var → `./pyaggregate.toml` default. Note: this function reads an env var, making it technically impure — but it's config resolution at the shell boundary, which is acceptable.

**Testing:**

Tests must verify:
- Loading a valid TOML config produces correct `AppConfig`
- Missing required fields raise `ValueError` with clear message
- Per-table overrides in `[agg.qa.tables.ae]` are parsed correctly
- `exclude_from_rollup` defaults to empty tuple when not specified
- Config resolution: CLI flag takes precedence over env var, env var over default

Follow project testing patterns.

**Verification:**

Run: `pytest tests/test_config.py -v`

Expected: All tests pass.

**Commit:** `feat: add TOML config loader with frozen dataclasses`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Test config loader

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC1.1, pyaggregate-unify-qa-qm-sdd.AC1.2

**Files:**
- Create: `tests/test_config.py`

**Testing:**

Tests must verify:
- Valid config: load `examples/pyaggregate.toml` (or a `tmp_path` copy of it) and assert all fields are populated correctly
- Missing `[scan]` section raises `ValueError`
- Missing `requests_root` in `[scan]` raises `ValueError`
- Per-table override: a config with `[agg.qa.tables.ae]` containing `rollup_keys = ["col1", "col2"]` is parsed into `TableOverride`
- `exclude_from_rollup` defaults: a config with no `exclude_from_rollup` in an agg type results in an empty tuple
- Config path resolution precedence: write a config to `tmp_path`, set env var, verify it's found; then pass CLI path, verify CLI wins
- All dataclasses are frozen (attempting to mutate raises `FrozenInstanceError`)

**Verification:**

Run: `pytest tests/test_config.py -v`

Expected: All tests pass.

**Commit:** `test: add config loader tests`

<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Wire config resolution into CLI

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC1.2

**Files:**
- Modify: `src/pyaggregate/cli.py`

**Implementation:**

Add a `--config` option to the typer app as a callback. This provides config resolution for all subcommands that need it. At this stage, the callback resolves and validates the config path but does not load the full config (subcommands will do that themselves in later phases).

Add a `typer.Option` for `--config` with `envvar="PYAGGREGATE_CONFIG"` and a default of `./pyaggregate.toml`.

**Testing:**

No new tests — this wiring is verified operationally via `pyaggregate --help` confirming the `--config` option appears.

**Verification:**

Run: `pyaggregate --help`

Expected: Shows `--config` option in help output.

Run: `ruff check src/ tests/ && ruff format --check src/ tests/`

Expected: No lint or format errors.

**Commit:** `feat: wire --config option into CLI`

<!-- END_TASK_5 -->

<!-- END_SUBCOMPONENT_B -->
