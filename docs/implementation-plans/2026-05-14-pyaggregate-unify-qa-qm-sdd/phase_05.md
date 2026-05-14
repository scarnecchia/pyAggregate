# pyAggregate — Phase 5: Aggregation pipeline (stacked + masked)

**Goal:** Read sas7bdat inputs per agg_type per table, produce `stacked` and `masked` DataFrames.

**Architecture:** Functional Core for dpid_mask and pipeline orchestration. Imperative Shell for sas_reader (I/O). Input resolution is a pure function that derives per-agg-type paths from a catalog snapshot.

**Tech Stack:** Python 3.11+, polars, polars-readstat (`scan_readstat`, `ScanReadstat`), hypothesis

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield. Phases 1-4 create scaffold, paths, config, catalog store, and scanner. polars-readstat API confirmed: `scan_readstat(str(path), schema_overrides=..., preserve_order=False)` returns LazyFrame.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pyaggregate-unify-qa-qm-sdd.AC3: Aggregation produces the three expected outputs per table
- **pyaggregate-unify-qa-qm-sdd.AC3.1 Success:** For each table in the `qa` config, `outputs/qa/<run_id>/stacked/<table>.parquet` exists and contains rows from every catalog row where `reqtype = 'qar'`.
- **pyaggregate-unify-qa-qm-sdd.AC3.2 Success:** Stacked output preserves the real `dpid` column with values matching catalog `dpid`s.
- **pyaggregate-unify-qa-qm-sdd.AC3.3 Success:** `outputs/qa/<run_id>/masked/<table>.parquet` row count equals stacked row count, contains a `surrogate_id` column, and contains NO column named `dpid`.

### pyaggregate-unify-qa-qm-sdd.AC5: DPID surrogate mapping is stable and auto-extending
- **pyaggregate-unify-qa-qm-sdd.AC5.1 Success:** A DPID seen in a previous run receives the same surrogate_id in subsequent runs (across multiple `run` invocations spanning multiple scans).
- **pyaggregate-unify-qa-qm-sdd.AC5.2 Success:** A newly-observed DPID receives a fresh surrogate_id never previously assigned, and is added to `dpid_map` automatically.

### pyaggregate-unify-qa-qm-sdd.AC6: SDD aggregation pulls from both qar and qmr packages
- **pyaggregate-unify-qa-qm-sdd.AC6.1 Success:** Given a DP with both `soc_qar_wp041_<dp>_v01/msoc/scdm_snapshot/` and `soc_qmr_wp041_<dp>_v01/msoc/scdm_snapshot/` populated with complementary file sets, the SDD output contains rows derived from BOTH subtrees.
- **pyaggregate-unify-qa-qm-sdd.AC6.2 Success:** Given a DP where only the qar package's scdm_snapshot exists (qmr not yet returned), SDD includes the qar contribution and does not error on the missing qmr side.
- **pyaggregate-unify-qa-qm-sdd.AC6.3 Failure:** If a file with the same name appears in BOTH the qar and qmr scdm_snapshot for the same `(dpid, wpid)` (collision rather than complementary), the run logs a WARN naming the conflicting file and includes both rows in stacked output (no silent dedup).

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Implement SAS reader wrapper in io/sas_reader.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.1 (reading source files)

**Files:**
- Create: `src/pyaggregate/io/sas_reader.py`

**Implementation:**

Create `src/pyaggregate/io/sas_reader.py` with `# pattern: Imperative Shell` on line 1.

Implement:
- `read_table(msoc_path: Path, table_name: str, dpid: str, schema_overrides: dict[str, polars.DataType] | None = None) -> polars.LazyFrame` — uses `polars_readstat.scan_readstat(str(sas_path), schema_overrides=schema_overrides or {}, preserve_order=False)` to lazily scan a `.sas7bdat` file. Lowercases all column names via `.select(pl.all().name.to_lowercase())`. Injects a `dpid` column with the given value via `.with_columns(pl.lit(dpid).alias("dpid"))`. The `sas_path` is constructed as `msoc_path / f"{table_name}.sas7bdat"`. Per programming standards section 4.1, callers should pass explicit `schema_overrides` for identifier columns (e.g., `{"patid": pl.Int64}`) to prevent polars-readstat from inferring narrow types that silently truncate large SAS numeric identifiers.
- `read_metadata(sas_path: Path) -> dict` — uses `polars_readstat.ScanReadstat(str(sas_path)).metadata` for metadata-only reads (schema validation without loading data).
- `glob_tables(msoc_path: Path, exclude_subdirs: tuple[str, ...] = ("scdm_snapshot",)) -> list[str]` — lists `.sas7bdat` files directly under `msoc_path` (not in subdirectories), returns table names (stem without extension). Excludes files in `exclude_subdirs` subdirectories.
- `glob_scdm_tables(msoc_path: Path) -> list[str]` — lists `.sas7bdat` files under `msoc_path/scdm_snapshot/`, returns table names.

Follow the `scdm_parquet_tide` pattern: isolate `scan_readstat` call in a thin wrapper function to enable test patching when needed.

**Testing:**

Tests for the reader require real `.sas7bdat` files or mocking. Since creating synthetic SAS files is non-trivial, mock the `scan_readstat` call in unit tests and verify the wrapper logic (column lowercasing, dpid injection, glob patterns). The e2e test in Phase 8 will use real synthetic SAS fixtures.

Follow project testing patterns.

**Verification:**

Run: `pytest tests/test_sas_reader.py -v` (if created)

Expected: All tests pass.

**Commit:** `feat: add polars-readstat SAS reader wrapper`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Implement input resolution helper

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.1, pyaggregate-unify-qa-qm-sdd.AC6.1, pyaggregate-unify-qa-qm-sdd.AC6.2

**Files:**
- Create: `src/pyaggregate/core/input_resolution.py`
- Create: `src/pyaggregate/io/input_resolver.py`

**Implementation:**

The input resolution logic is split into a pure core function and a thin I/O wrapper, respecting the FCIS boundary.

**Pure core** — Create `src/pyaggregate/core/input_resolution.py` with `# pattern: Functional Core` on line 1.

Implement a frozen dataclass `TableInput`:
- `dpid: str`
- `msoc_path: Path`
- `reqtype: str`

Implement `filter_catalog(catalog: polars.DataFrame, agg_config: AggTypeConfig) -> polars.DataFrame` that:
- For `qa`/`qm` (source_reqtype set): filters catalog to `reqtype == agg_config.source_reqtype`
- For `sdd` (source_field set): filters catalog to `agg_config.source_field == 1` (e.g., `has_scdm == 1`)
- Returns the filtered DataFrame — pure function, no I/O

Implement `group_inputs_by_table(table_listings: list[tuple[str, str, Path, str]], agg_config: AggTypeConfig) -> dict[str, list[TableInput]]` that:
- Takes pre-resolved `(table_name, dpid, msoc_path, reqtype)` tuples (the caller has already globbed the filesystem)
- Groups by table_name, returns `dict[str, list[TableInput]]`
- Pure function — no I/O

Implement `detect_sdd_collisions(inputs: dict[str, list[TableInput]]) -> list[str]` that checks for same filename from both qar and qmr for the same `(dpid, wpid)`. Returns warning messages for each collision found (AC6.3). Pure function.

**I/O wrapper** — Create `src/pyaggregate/io/input_resolver.py` with `# pattern: Imperative Shell` on line 1.

Implement `resolve_inputs(catalog: polars.DataFrame, agg_config: AggTypeConfig) -> dict[str, list[TableInput]]` that:
- Calls `filter_catalog` (pure) to get relevant catalog rows
- For each row, globs `msoc_path/*.sas7bdat` (for qa/qm, excluding `agg_config.subdirectory` if set) or `msoc_path/{agg_config.subdirectory}/*.sas7bdat` (for sdd, where `subdirectory` is read from config, e.g., `"scdm_snapshot"`) — this is the I/O. The `subdirectory` config field drives the glob pattern, making SDD resolution config-driven rather than hardcoded.
- Passes the resolved `(table_name, dpid, msoc_path, reqtype)` tuples to `group_inputs_by_table` (pure)
- Returns the grouped result

**Testing:**

Tests must verify:
- AC3.1: `qa` config resolves only qar rows from catalog
- AC6.1: `sdd` config resolves both qar and qmr scdm_snapshot paths for same DP
- AC6.2: `sdd` config handles missing qmr side gracefully (only qar contributes)
- AC6.3: Collision detection identifies same filename from both reqtypes
- Table grouping: multiple DPs contributing to same table name are grouped correctly

Follow project testing patterns.

**Verification:**

Run: `pytest tests/test_input_resolution.py -v`

Expected: All tests pass.

**Commit:** `feat: add input resolution for qa, qm, and sdd aggregation types`

<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-5) -->

<!-- START_TASK_3 -->
### Task 3: Implement dpid_mask in core/dpid_mask.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.3, pyaggregate-unify-qa-qm-sdd.AC5.1, pyaggregate-unify-qa-qm-sdd.AC5.2

**Files:**
- Create: `src/pyaggregate/core/dpid_mask.py`

**Implementation:**

Create `src/pyaggregate/core/dpid_mask.py` with `# pattern: Functional Core` on line 1.

Implement `mask_dpid(frame: polars.DataFrame, dpid_map: polars.DataFrame) -> polars.DataFrame`:
- Left-join `frame` on `dpid` column to `dpid_map` (which has `dpid` → `surrogate_id` mapping)
- Drop the original `dpid` column
- The result has `surrogate_id` in place of `dpid`
- Row count must be preserved (no rows lost in join)

The function is pure — both inputs are DataFrames, output is a DataFrame. The `dpid_map` DataFrame is passed in from the caller (CatalogStore snapshot), keeping this module free of I/O.

**Testing:**

Tests must verify:
- AC3.3: Masked output has `surrogate_id` column, no `dpid` column
- AC3.3: Row count equals input row count
- AC5.1: Same dpid → same surrogate_id (test with dpid_map fixture)
- AC5.2: All dpids in frame must have a mapping in dpid_map (test that unmapped dpid produces null surrogate — this is a data integrity signal)

Follow project testing patterns.

**Verification:**

Run: `pytest tests/test_dpid_mask.py -v`

Expected: All tests pass.

**Commit:** `feat: add pure dpid masking function`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Test dpid_mask with hypothesis

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.3, pyaggregate-unify-qa-qm-sdd.AC5.1, pyaggregate-unify-qa-qm-sdd.AC5.2

**Files:**
- Create: `tests/test_dpid_mask.py`

**Testing:**

Use `hypothesis` property-based tests:

Property tests:
- **Row count preserved:** For any input DataFrame with a `dpid` column and any valid `dpid_map`, `mask_dpid(frame, dpid_map).height == frame.height`
- **No dpid leakage:** `"dpid" not in mask_dpid(frame, dpid_map).columns`
- **Surrogate present:** `"surrogate_id" in mask_dpid(frame, dpid_map).columns`
- **Surrogate uniqueness per dpid:** Each unique dpid maps to exactly one unique surrogate_id (no many-to-one collisions)

Example-based tests:
- 3 DPs (`aeos`, `cms`, `kpsc`) with known surrogate mapping → verify exact surrogate values in output
- Empty DataFrame → returns empty DataFrame with correct schema
- Single-row DataFrame → correct surrogate substitution

**Verification:**

Run: `pytest tests/test_dpid_mask.py -v`

Expected: All tests pass.

**Commit:** `test: add dpid mask property tests with hypothesis`

<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Implement pipeline orchestration in core/pipeline.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.1, pyaggregate-unify-qa-qm-sdd.AC3.2, pyaggregate-unify-qa-qm-sdd.AC3.3

**Files:**
- Create: `src/pyaggregate/core/pipeline.py`

**Implementation:**

Create `src/pyaggregate/core/pipeline.py` with `# pattern: Functional Core` on line 1.

Implement `aggregate_table(table_inputs: list[TableInput], dpid_map: polars.DataFrame, agg_config: AggTypeConfig, table_name: str, reader_fn: Callable) -> dict[str, polars.DataFrame]`:

1. **Stack:** For each `TableInput`, call `reader_fn(input.msoc_path, table_name, input.dpid)` to get a LazyFrame. Before concatenation, collect schemas from all frames and check for type conflicts (e.g., one DP sends a column as Int64 while another sends it as Float64). When type conflicts are detected, upcast to the safest common type (Int64→Float64, any→Utf8 as last resort) and log a warning naming the column and conflicting types. Then use `polars.concat(frames, how="diagonal")` to handle structural drift (missing/added columns filled with nulls). Log a warning when schemas differ between frames, naming the columns that were added/missing. Collect to DataFrame. This is the `stacked` output — preserves the real `dpid` column (AC3.2).

2. **Mask:** Call `mask_dpid(stacked, dpid_map)` to produce the `masked` output — `dpid` replaced with `surrogate_id` (AC3.3).

3. Return `{"stacked": stacked, "masked": masked}`. (Rollup is added in Phase 6.)

The `reader_fn` parameter is a callable (dependency injection) so the pipeline can be tested without real SAS files. In production, this is `sas_reader.read_table`.

**Testing:**

Tests must verify:
- AC3.1: Stacked output contains rows from all contributing DPs
- AC3.2: Stacked output has `dpid` column with correct values
- AC3.3: Masked output has `surrogate_id`, no `dpid`, same row count as stacked

Use synthetic DataFrames (not real SAS files) by passing a fake `reader_fn`.

Follow project testing patterns.

**Verification:**

Run: `pytest tests/test_pipeline_stacked.py -v`

Expected: All tests pass.

**Commit:** `feat: add pipeline orchestration for stacked and masked outputs`

<!-- END_TASK_5 -->

<!-- END_SUBCOMPONENT_B -->

<!-- START_TASK_6 -->
### Task 6: Test pipeline stacked output

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.1, pyaggregate-unify-qa-qm-sdd.AC3.2, pyaggregate-unify-qa-qm-sdd.AC3.3

**Files:**
- Create: `tests/test_pipeline_stacked.py`

**Testing:**

Create a fake `reader_fn` that returns synthetic polars LazyFrames for testing:

```python
def fake_reader(msoc_path: Path, table_name: str, dpid: str) -> pl.LazyFrame:
    # Return a small synthetic frame with known data
    ...
```

Tests must cover:
- 3 DPs, each contributing 5 rows → stacked has 15 rows with all 3 dpids
- Stacked preserves real dpid values (not surrogates)
- Masked has surrogate_id column, no dpid column
- Masked row count equals stacked row count
- Empty inputs (no contributing DPs) → empty DataFrames with correct schema
- Single DP → stacked and masked both have that DP's rows
- Schema drift: two DPs with different columns (one has extra column) → stacked uses `how="diagonal"`, extra column filled with null for the DP that lacks it, no crash

**Verification:**

Run: `pytest tests/test_pipeline_stacked.py -v`

Expected: All tests pass.

**Commit:** `test: add pipeline stacked and masked output tests`

<!-- END_TASK_6 -->

<!-- START_TASK_7 -->
### Task 7: Test input resolution

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC6.1, pyaggregate-unify-qa-qm-sdd.AC6.2, pyaggregate-unify-qa-qm-sdd.AC6.3

**Files:**
- Create: `tests/test_input_resolution.py`

**Testing:**

Create a catalog snapshot as a polars DataFrame fixture:

```python
catalog = pl.DataFrame({
    "dpid": ["aeos", "aeos", "cms"],
    "wpid": ["wp041", "wp041", "wp041"],
    "reqtype": ["qar", "qmr", "qar"],
    "verid": ["v02", "v01", "v01"],
    "msoc_path": ["/data/aeos/qar/msoc", "/data/aeos/qmr/msoc", "/data/cms/qar/msoc"],
    "has_scdm": [1, 1, 0],
    "observed_at": ["2026-05-14T00:00:00", "2026-05-14T00:00:00", "2026-05-14T00:00:00"],
})
```

Tests must cover:
- `qa` resolves only qar rows: `aeos` (qar) and `cms` (qar), not `aeos` (qmr)
- `qm` resolves only qmr rows: `aeos` (qmr) only
- `sdd` resolves both reqtypes where `has_scdm=1`: both `aeos` qar and qmr
- AC6.2: DP with only qar scdm_snapshot (no qmr) → sdd includes qar contribution
- AC6.3: Collision detection with same filename from both reqtypes

**Verification:**

Run: `pytest tests/test_input_resolution.py -v`

Expected: All tests pass.

Run: `pytest tests/ -v`

Expected: All Phase 1-5 tests pass.

**Commit:** `test: add input resolution tests for qa, qm, and sdd`

<!-- END_TASK_7 -->
