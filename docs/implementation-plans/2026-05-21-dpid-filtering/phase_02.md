# Per-Agg-Type DPID Filtering Implementation Plan

**Goal:** Add per-aggregation-type DPID filtering so operators can restrict which data partners are included in each aggregation run.

**Architecture:** Pure filtering functions in Functional Core, orchestration in Imperative Shell, side effects (logging) in CLI. New `allowed_dpids` field on `AggTypeConfig` with TOML-level validation; pure `filter_allowed_dpids` and `check_unknown_dpids` functions wired into the existing `resolve_inputs` chain.

**Tech Stack:** Python 3.11+, Polars, TOML (tomllib), pytest

**Scope:** 3 phases from original design (phases 1-3)

**Codebase verified:** 2026-05-21

---

## Acceptance Criteria Coverage

This phase implements and tests:

### dpid-filtering.AC2: Filtering limits aggregation to allowed DPs
- **dpid-filtering.AC2.1 Success:** Specific DPIDs filter catalog to only matching rows
- **dpid-filtering.AC2.2 Success:** Wildcard `["*"]` returns catalog unchanged
- **dpid-filtering.AC2.3 Edge:** Empty list `[]` returns empty DataFrame
- **dpid-filtering.AC2.4 Edge:** All columns preserved after filtering (schema unchanged)
- **dpid-filtering.AC2.5 Edge:** DPID in allowed list but not in catalog produces empty result for that DPID (no error)

### dpid-filtering.AC3: Unknown DPIDs produce structured warnings
- **dpid-filtering.AC3.1 Success:** DPID in config but not in catalog generates warning string
- **dpid-filtering.AC3.2 Success:** Wildcard skips unknown-DPID check entirely (no warnings)
- **dpid-filtering.AC3.3 Success:** All DPIDs found in catalog produces no warnings

---

## Phase 2: Filtering and Warning Functions

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Implement `filter_allowed_dpids` and `check_unknown_dpids`

**Files:**
- Modify: `src/pyaggregate/core/input_resolution.py` (add two new functions after `filter_catalog` at line 57)

**Implementation:**

Add two pure functions to `src/pyaggregate/core/input_resolution.py` after the existing `filter_catalog` function (after line 57, before `select_latest_workplan_per_dp`).

**`filter_allowed_dpids`** — pure DataFrame filter:

```python
def filter_allowed_dpids(
    catalog: pl.DataFrame, allowed_dpids: tuple[str, ...]
) -> pl.DataFrame:
    """Filter catalog rows to only allowed data partners.

    Args:
        catalog: Catalog DataFrame with a 'dpid' column
        allowed_dpids: Tuple of lowercase DPID strings, or ("*",) for all

    Returns:
        Filtered DataFrame (unchanged if wildcard, empty if allowed_dpids is empty)
    """
    if "*" in allowed_dpids:
        return catalog
    return catalog.filter(pl.col("dpid").is_in(list(allowed_dpids)))
```

**`check_unknown_dpids`** — pure warning generator (follows `detect_snapshot_collisions` pattern of returning `list[str]`):

```python
def check_unknown_dpids(
    allowed_dpids: tuple[str, ...], catalog_dpids: set[str]
) -> list[str]:
    """Return warning strings for allowed DPIDs not found in the catalog.

    Args:
        allowed_dpids: Tuple of lowercase DPID strings, or ("*",) for all
        catalog_dpids: Set of DPIDs present in the catalog

    Returns:
        List of warning message strings (empty if wildcard or all found)
    """
    if "*" in allowed_dpids:
        return []
    unknown = sorted(set(allowed_dpids) - catalog_dpids)
    return [
        f"allowed_dpids contains '{dpid}' which was not found in the catalog"
        for dpid in unknown
    ]
```

**Verification:**
Run: `python -c "from pyaggregate.core.input_resolution import filter_allowed_dpids, check_unknown_dpids; print('imports ok')"`
Expected: `imports ok`

Run: `ruff check src/pyaggregate/core/input_resolution.py`
Expected: No lint errors.

Run: `mypy src/pyaggregate/core/input_resolution.py`
Expected: No type errors.

**Commit:** `feat(core): add filter_allowed_dpids and check_unknown_dpids functions`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add tests for `filter_allowed_dpids` and `check_unknown_dpids`

**Verifies:** dpid-filtering.AC2.1, dpid-filtering.AC2.2, dpid-filtering.AC2.3, dpid-filtering.AC2.4, dpid-filtering.AC2.5, dpid-filtering.AC3.1, dpid-filtering.AC3.2, dpid-filtering.AC3.3

**Files:**
- Modify: `tests/test_input_resolution.py` (add two new test classes and update imports)

**Implementation:**

Update the import block at line 11-18 to include the new functions:

```python
from pyaggregate.core.input_resolution import (
    TableInput,
    check_unknown_dpids,
    detect_snapshot_collisions,
    filter_allowed_dpids,
    filter_catalog,
    group_inputs_by_table,
    select_latest_workplan_per_dp,
    wpid_sort_key,
)
```

Add two new test classes after `TestFilterCatalog` (after line 124) and before `TestWpidSortKey`.

**`TestFilterAllowedDpids`** — tests using inline Polars DataFrames (same pattern as existing `TestFilterCatalog` and `TestSelectLatestWorkplanPerDp`):

Tests must verify each AC listed:
- **dpid-filtering.AC2.1:** Create catalog with dpids `["aeos", "cms", "nsdp"]`, filter with `allowed_dpids=("aeos", "cms")`, assert only `aeos` and `cms` rows remain
- **dpid-filtering.AC2.2:** Same catalog, filter with `allowed_dpids=("*",)`, assert all rows returned unchanged (same height as input)
- **dpid-filtering.AC2.3:** Same catalog, filter with `allowed_dpids=()`, assert result is empty DataFrame
- **dpid-filtering.AC2.4:** Filter with specific DPIDs, assert `set(result.columns) == set(catalog.columns)` (same pattern as `test_filter_catalog_preserves_all_columns` at line 111)
- **dpid-filtering.AC2.5:** Create catalog with dpids `["aeos", "cms"]`, filter with `allowed_dpids=("aeos", "unknown_dp")`, assert only `aeos` rows remain (no error raised for `unknown_dp`)

Use the same catalog column schema as the existing `CatalogFixture`: `dpid`, `wpid`, `reqtype`, `verid`, `msoc_path`, `has_scdm`, `observed_at`.

**`TestCheckUnknownDpids`** — tests for the pure warning generator (same pattern as `TestDetectSnapshotCollisions` at line 321):

Tests must verify each AC listed:
- **dpid-filtering.AC3.1:** Call with `allowed_dpids=("aeos", "unknown_dp")` and `catalog_dpids={"aeos", "cms"}`, assert result contains one warning string mentioning `"unknown_dp"`
- **dpid-filtering.AC3.2:** Call with `allowed_dpids=("*",)` and any `catalog_dpids`, assert result is empty list
- **dpid-filtering.AC3.3:** Call with `allowed_dpids=("aeos", "cms")` and `catalog_dpids={"aeos", "cms"}`, assert result is empty list

Follow project testing patterns: class-based tests, direct assertions, `pytest.raises` not needed here (no exceptions expected).

**Verification:**
Run: `pytest tests/test_input_resolution.py -v -k "FilterAllowedDpids or CheckUnknownDpids"`
Expected: All new tests pass.

Run: `pytest tests/test_input_resolution.py -v`
Expected: All tests pass (existing + new).

Run: `ruff check tests/test_input_resolution.py`
Expected: No lint errors.

**Commit:** `test: add tests for DPID filtering and unknown DPID warnings`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->
