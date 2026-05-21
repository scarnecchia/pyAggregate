# Per-Agg-Type DPID Filtering Implementation Plan

**Goal:** Add per-aggregation-type DPID filtering so operators can restrict which data partners are included in each aggregation run.

**Architecture:** Pure filtering functions in Functional Core, orchestration in Imperative Shell, side effects (logging) in CLI. New `allowed_dpids` field on `AggTypeConfig` with TOML-level validation; pure `filter_allowed_dpids` and `check_unknown_dpids` functions wired into the existing `resolve_inputs` chain.

**Tech Stack:** Python 3.11+, Polars, TOML (tomllib), pytest

**Scope:** 3 phases from original design (phases 1-3)

**Codebase verified:** 2026-05-21

---

## Acceptance Criteria Coverage

This phase implements and tests:

### dpid-filtering.AC4: End-to-end pipeline integration
- **dpid-filtering.AC4.1 Success:** `resolve_inputs` applies DPID filter between `filter_catalog` and `select_latest_workplan_per_dp`
- **dpid-filtering.AC4.2 Success:** CLI run command logs warnings for unknown DPIDs via structured logger
- **dpid-filtering.AC4.3 Success:** Downstream outputs (dpid_map, manifest) naturally exclude filtered-out DPs without code changes

### dpid-filtering.AC5: Scan behaviour unchanged
- **dpid-filtering.AC5.1 Success:** Scan catalogs all DPs regardless of any `allowed_dpids` config

---

## Phase 3: Orchestration Wiring

<!-- START_TASK_1 -->
### Task 1: Wire `filter_allowed_dpids` into `resolve_inputs`

**Verifies:** dpid-filtering.AC4.1

**Files:**
- Modify: `src/pyaggregate/io/input_resolver.py:9-14` (imports), `src/pyaggregate/io/input_resolver.py:46-50` (filter chain)

**Implementation:**

**Step 1: Update imports** in `src/pyaggregate/io/input_resolver.py` (lines 9-14).

Add `filter_allowed_dpids` to the import from `pyaggregate.core.input_resolution`:

```python
from pyaggregate.core.input_resolution import (
    TableInput,
    filter_allowed_dpids,
    filter_catalog,
    group_inputs_by_table,
    select_latest_workplan_per_dp,
)
```

**Step 2: Insert DPID filter** between `filter_catalog` and `select_latest_workplan_per_dp` in `resolve_inputs` (between lines 46 and 50).

Current code at lines 45-50:
```python
    # Filter catalog to relevant rows
    filtered_catalog = filter_catalog(catalog, agg_config)

    # Narrow to highest wpid per (dpid, reqtype)
    filtered_catalog = select_latest_workplan_per_dp(filtered_catalog)
```

Becomes:
```python
    # Filter catalog to relevant rows
    filtered_catalog = filter_catalog(catalog, agg_config)

    # Apply DPID allowlist filter
    filtered_catalog = filter_allowed_dpids(
        filtered_catalog, agg_config.allowed_dpids
    )

    # Narrow to highest wpid per (dpid, reqtype)
    filtered_catalog = select_latest_workplan_per_dp(filtered_catalog)
```

**Verification:**
Run: `ruff check src/pyaggregate/io/input_resolver.py`
Expected: No lint errors.

Run: `mypy src/pyaggregate/io/input_resolver.py`
Expected: No type errors.

**Commit:** `feat(io): wire filter_allowed_dpids into resolve_inputs`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add unknown-DPID warning logging to CLI run command

**Verifies:** dpid-filtering.AC4.2

**Files:**
- Modify: `src/pyaggregate/cli.py:154-155` (imports), `src/pyaggregate/cli.py:198-203` (warning check insertion)

**Implementation:**

**Step 1: Add import** for `check_unknown_dpids`.

At the top of the `run` function (line 154-156, inside the `try` block's import section), add:

```python
from pyaggregate.core.input_resolution import check_unknown_dpids
```

**Step 2: Insert warning check** after catalog snapshot and before `resolve_inputs`.

Insert between line 200 (`dpid_map_df = store.snapshot_dpid_map()`) and line 203 (`table_inputs_dict = resolve_inputs(catalog_df, agg_config)`). The code goes after the `with CatalogStore` block closes (after line 200) and before the `resolve_inputs` call:

```python
            # Check for unknown DPIDs in allowed_dpids config
            catalog_dpids = set(catalog_df["dpid"].unique().to_list())
            unknown_warnings = check_unknown_dpids(
                agg_config.allowed_dpids, catalog_dpids
            )
            if unknown_warnings:
                run_logger = logging.getLogger("pyaggregate.run.inputs")
                for warning_msg in unknown_warnings:
                    run_logger.warning(
                        warning_msg,
                        extra={
                            "run_id": run_id,
                            "agg_type": agg_type,
                        },
                    )
```

Note: `run_logger` is also created later at line 209. Move the logger creation earlier (before the unknown DPID check) to avoid creating it twice. Or simply use `logging.getLogger("pyaggregate.run.inputs")` inline since `getLogger` returns the same object for the same name — the existing code already does this at line 209, so the two calls will share the same logger instance. No change to line 209 needed.

Note: `catalog_dpids` is extracted inside the per-agg-type loop, so it's recomputed each iteration. This is structurally constrained because the `CatalogStore` context (and therefore `catalog_df`) is opened per agg type at cli.py:198-200. The extraction is cheap (unique on a small column) so this is acceptable. Hoisting the catalog snapshot outside the loop would be a separate refactor.

**Verification:**
Run: `ruff check src/pyaggregate/cli.py`
Expected: No lint errors.

Run: `mypy src/pyaggregate/cli.py`
Expected: No type errors.

**Commit:** `feat(cli): log warnings for unknown DPIDs in allowed_dpids`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Update all test fixtures with `allowed_dpids` in TOML configs

**Files:**
- Modify: `tests/test_run_orchestration.py:74-98` (TOML string)
- Modify: `tests/test_e2e_smoke.py:101-124` (TOML string)

**Implementation:**

Direct Python `AggTypeConfig` constructions across test files (`test_run_orchestration.py:66-69`, `test_input_resolution.py`, `test_pipeline_rollup.py`, `test_pipeline_stacked.py`, `test_stats_exclusion.py`) do NOT need updating — the dataclass default `("*",)` preserves current behaviour. Only TOML config strings need `allowed_dpids` added because `load_config` validates its presence.

**Step 1: Update `test_run_orchestration.py` TOML string (lines 74-98)**

Add `allowed_dpids = ["*"]` to each `[agg.<name>]` block in the inline TOML string:

```
[agg.qa]
source_reqtype = "qar"
output_path = "{}"
exclude_from_rollup = ["*_stats"]
allowed_dpids = ["*"]

[agg.qm]
source_reqtype = "qmr"
output_path = "{}"
exclude_from_rollup = ["*_stats"]
allowed_dpids = ["*"]

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "{}"
exclude_from_rollup = []
allowed_dpids = ["*"]
```

**Step 3: Update `test_e2e_smoke.py` TOML string (lines 101-124)**

Add `allowed_dpids = ["*"]` to each `[agg.<name>]` block:

```
[agg.qa]
output_path = "{output_dir / "qa"}"
source_reqtype = "qar"
exclude_from_rollup = []
allowed_dpids = ["*"]

[agg.qm]
output_path = "{output_dir / "qm"}"
source_reqtype = "qmr"
exclude_from_rollup = []
allowed_dpids = ["*"]

[agg.snapshot]
output_path = "{output_dir / "snapshot"}"
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
exclude_from_rollup = []
allowed_dpids = ["*"]
```

**Verification:**
Run: `pytest tests/test_run_orchestration.py tests/test_e2e_smoke.py -v -x`
Expected: All existing tests pass with `allowed_dpids` added.

**Commit:** `test: add allowed_dpids to test fixtures and TOML configs`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Add integration test for DPID filtering in `resolve_inputs`

**Verifies:** dpid-filtering.AC4.1, dpid-filtering.AC4.3, dpid-filtering.AC5.1

**Files:**
- Modify: `tests/test_input_resolution.py` (add test to `TestResolveInputs` class, lines 371-498)

**Implementation:**

Add a new test to the `TestResolveInputs` class that verifies `resolve_inputs` respects `allowed_dpids` filtering.

Tests must verify:
- **dpid-filtering.AC4.1:** Create a catalog with two DPs (`aeos`, `cms`), pass `AggTypeConfig` with `allowed_dpids=("aeos",)`, mock `glob_tables`, assert only `aeos` inputs appear in result — `cms` is filtered out before globbing
- **dpid-filtering.AC4.3:** The result naturally excludes filtered-out DPs without any downstream changes — if `cms` is filtered out, its tables simply don't appear in the output dict
- **dpid-filtering.AC5.1:** Scan behaviour is unchanged — verified by existing scan tests (`test_scanner.py`, `test_scanner_concurrency.py`) remaining unmodified and passing. The FCIS boundary enforces this: the scanner lives in `io/scanner.py` and has no import path to `filter_allowed_dpids` (which lives in `core/input_resolution.py` and is only called from `io/input_resolver.py`). No explicit assertion is added for this AC — the architectural boundary is the guard. Add a brief comment in the test noting this.

Follow the existing `TestResolveInputs` pattern: `tmp_path` fixture, inline Polars DataFrame, `patch("pyaggregate.io.input_resolver.glob_tables")`.

**Verification:**
Run: `pytest tests/test_input_resolution.py::TestResolveInputs -v`
Expected: All tests pass including the new one.

Run: `pytest tests/ -v -x`
Expected: Full test suite passes.

Run: `ruff check src/ tests/`
Expected: No lint errors.

Run: `mypy src/`
Expected: No type errors.

**Commit:** `test: add integration test for DPID filtering in resolve_inputs`
<!-- END_TASK_4 -->
