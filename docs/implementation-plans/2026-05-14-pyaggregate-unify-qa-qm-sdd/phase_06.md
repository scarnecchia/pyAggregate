# pyAggregate — Phase 6: Rollup and `_stats` exclusion

**Goal:** Add the third output (rollup) and enforce per-table rollup-exclusion patterns.

**Architecture:** Functional Core — rollup logic is a pure function in `core/pipeline.py`. Exclusion matching is config-driven.

**Tech Stack:** Python 3.11+, polars (`group_by`, `agg`), `fnmatch` (stdlib)

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield. Phase 5 creates `pipeline.py` with stacked and masked outputs.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### pyaggregate-unify-qa-qm-sdd.AC3: Aggregation produces the three expected outputs per table
- **pyaggregate-unify-qa-qm-sdd.AC3.4 Success:** `outputs/qa/<run_id>/rollup/<table>.parquet` contains no `dpid` and no `surrogate_id` columns; sum over numeric columns equals the corresponding sum in stacked.
- **pyaggregate-unify-qa-qm-sdd.AC3.5 Success:** Rollup row count is less than or equal to stacked row count (collapses identical key combinations across DPs).

### pyaggregate-unify-qa-qm-sdd.AC7: `*_stats` exclusion applies to rollup only
- **pyaggregate-unify-qa-qm-sdd.AC7.1 Success:** Tables matching any pattern in `agg.<type>.exclude_from_rollup` produce `stacked.parquet` and `masked.parquet` but NO `rollup.parquet`.
- **pyaggregate-unify-qa-qm-sdd.AC7.2 Success:** Non-matching tables in the same agg_type produce all three outputs.

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Implement rollup function in core/pipeline.py

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.4, pyaggregate-unify-qa-qm-sdd.AC3.5

**Files:**
- Modify: `src/pyaggregate/core/pipeline.py`

**Implementation:**

Add a `compute_rollup(stacked: polars.DataFrame, rollup_keys: list[str] | None, rollup_aggs: dict[str, str] | None) -> polars.DataFrame` function to `core/pipeline.py`.

Behaviour:
- Drop `dpid` column (real DP identifier must not appear in rollup)
- Drop `surrogate_id` column if present (surrogates also excluded from rollup per AC3.4)
- If `rollup_keys` is `None`, default to all non-numeric columns remaining after drops
- If `rollup_aggs` is `None`, default to `sum` for all numeric columns
- Group by `rollup_keys`, apply `rollup_aggs`
- Return the resulting DataFrame

The function is pure — it takes a DataFrame and returns a DataFrame.

Also extend `aggregate_table` (from Phase 5) to call `compute_rollup` and include `'rollup'` in its output dict.

**Testing:**

Tests must verify:
- AC3.4: Rollup output contains no `dpid` or `surrogate_id` columns
- AC3.4: Sum of numeric columns in rollup equals sum in stacked
- AC3.5: Rollup row count <= stacked row count
- Default rollup keys: when not specified, all non-numeric columns are used as keys
- Custom rollup keys: when specified via config, only those columns are used
- Custom rollup aggs: when specified, those aggregation functions are applied

Follow project testing patterns.

**Verification:**

Run: `pytest tests/test_pipeline_rollup.py -v`

Expected: All tests pass.

**Commit:** `feat: add rollup aggregation to pipeline`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Test rollup with hypothesis property tests

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC3.4, pyaggregate-unify-qa-qm-sdd.AC3.5

**Files:**
- Create: `tests/test_pipeline_rollup.py`

**Testing:**

Use `hypothesis` property-based tests to verify rollup invariants:

Property tests:
- **Row count invariant:** For any synthetic DataFrame with a `dpid` column and numeric columns, `rollup.height <= stacked.height`
- **Sum preservation:** For any numeric column, `rollup[col].sum() == stacked[col].sum()` (within floating point tolerance via `pytest.approx`)
- **No dpid leakage:** `"dpid" not in rollup.columns` and `"surrogate_id" not in rollup.columns`
- **Schema stability:** Rollup columns are a subset of stacked columns minus `dpid` and `surrogate_id`

Example-based tests:
- Three DPs with identical key values → rollup collapses to 1 row, sums are correct
- Three DPs with distinct key values → rollup row count equals stacked row count
- Mixed: some shared keys, some unique → rollup count between 1 and stacked count

**Verification:**

Run: `pytest tests/test_pipeline_rollup.py -v`

Expected: All tests pass.

**Commit:** `test: add rollup property tests with hypothesis`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Implement _stats exclusion logic

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC7.1, pyaggregate-unify-qa-qm-sdd.AC7.2

**Files:**
- Modify: `src/pyaggregate/core/pipeline.py`

**Implementation:**

Add a `should_exclude_rollup(table_name: str, exclude_patterns: tuple[str, ...]) -> bool` function that uses `fnmatch.fnmatch` to check if the table name matches any exclusion pattern (e.g., `*_stats`).

Modify `aggregate_table` to check `should_exclude_rollup` before computing rollup. If excluded, the output dict contains `'stacked'` and `'masked'` but NOT `'rollup'`.

**Testing:**

Tests must verify:
- AC7.1: Table `ae_stats` with config `exclude_from_rollup = ["*_stats"]` → output dict has `stacked` and `masked` but no `rollup`
- AC7.2: Table `ae` with same config → output dict has all three keys
- Multiple patterns: `["*_stats", "lab_*"]` excludes both `ae_stats` and `lab_results`
- Empty patterns: `[]` excludes nothing, all tables get rollup

Follow project testing patterns.

**Verification:**

Run: `pytest tests/test_stats_exclusion.py -v`

Expected: All tests pass.

**Commit:** `feat: add rollup exclusion for _stats tables`

<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_4 -->
### Task 4: Test _stats exclusion

**Verifies:** pyaggregate-unify-qa-qm-sdd.AC7.1, pyaggregate-unify-qa-qm-sdd.AC7.2

**Files:**
- Create: `tests/test_stats_exclusion.py`

**Testing:**

Create focused tests for the exclusion logic:
- `should_exclude_rollup("ae_stats", ("*_stats",))` → `True`
- `should_exclude_rollup("ae", ("*_stats",))` → `False`
- `should_exclude_rollup("lab_results", ("*_stats", "lab_*"))` → `True`
- `should_exclude_rollup("ae", ())` → `False` (empty exclusion list)
- Integration: run `aggregate_table` with an excluded table, verify output dict keys

**Verification:**

Run: `pytest tests/test_stats_exclusion.py -v`

Expected: All tests pass.

Run: `pytest tests/test_pipeline_rollup.py tests/test_stats_exclusion.py -v`

Expected: All rollup and exclusion tests pass.

**Commit:** `test: add stats exclusion tests`

<!-- END_TASK_4 -->
