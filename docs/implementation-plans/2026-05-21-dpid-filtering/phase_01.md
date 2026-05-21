# Per-Agg-Type DPID Filtering Implementation Plan

**Goal:** Add per-aggregation-type DPID filtering so operators can restrict which data partners are included in each aggregation run.

**Architecture:** Pure filtering functions in Functional Core, orchestration in Imperative Shell, side effects (logging) in CLI. New `allowed_dpids` field on `AggTypeConfig` with TOML-level validation; pure `filter_allowed_dpids` and `check_unknown_dpids` functions wired into the existing `resolve_inputs` chain.

**Tech Stack:** Python 3.11+, Polars, TOML (tomllib), pytest

**Scope:** 3 phases from original design (phases 1-3)

**Codebase verified:** 2026-05-21

---

## Acceptance Criteria Coverage

This phase implements and tests:

### dpid-filtering.AC1: Config requires allowed_dpids
- **dpid-filtering.AC1.1 Success:** `allowed_dpids = ["msoc", "nsdp"]` parses into `tuple[str, ...]`
- **dpid-filtering.AC1.2 Success:** `allowed_dpids = ["*"]` parses without error
- **dpid-filtering.AC1.3 Success:** `allowed_dpids = []` parses without error
- **dpid-filtering.AC1.4 Failure:** Missing `allowed_dpids` raises `ValueError` with descriptive message
- **dpid-filtering.AC1.5 Failure:** Non-list value for `allowed_dpids` raises `ValueError`

---

## Phase 1: Config Field and Validation

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->
<!-- START_TASK_1 -->
### Task 1: Add `allowed_dpids` field to `AggTypeConfig`

**Files:**
- Modify: `src/pyaggregate/config.py:19-31`

**Implementation:**

Add `allowed_dpids: tuple[str, ...] = ("*",)` to the `AggTypeConfig` frozen dataclass. Place it after `exclude_from_rollup` (line 28) and before `table_overrides` (line 29). The default of `("*",)` preserves current all-inclusive behaviour for direct construction in tests, while `load_config` will enforce the field is present in TOML (Phase 1, Task 2).

The dataclass becomes:

```python
@dataclass(frozen=True)
class AggTypeConfig:
    """Configuration for an aggregation type."""

    name: str
    output_path: Path
    source_reqtype: str | None = None
    source_field: str | None = None
    subdirectory: str | None = None
    exclude_from_rollup: tuple[str, ...] = ()
    allowed_dpids: tuple[str, ...] = ("*",)
    table_overrides: MappingProxyType[str, TableOverride] = field(
        default_factory=lambda: MappingProxyType({})
    )
```

**Verification:**
Run: `python -c "from pyaggregate.config import AggTypeConfig; from pathlib import Path; a = AggTypeConfig(name='test', output_path=Path('/tmp')); print(a.allowed_dpids)"`
Expected: `('*',)`

**Commit:** `feat(config): add allowed_dpids field to AggTypeConfig`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Parse and validate `allowed_dpids` in `load_config`

**Files:**
- Modify: `src/pyaggregate/config.py:110-159` (inside the `for agg_name, agg_config` loop)

**Implementation:**

Add parsing and validation for `allowed_dpids` after the `exclude_from_rollup` parsing block (after line 130) and before the table overrides parsing (line 133). The field is **required** in TOML — missing raises `ValueError`. Non-list values also raise `ValueError`.

Insert this block after line 130 (`exclude_from_rollup = tuple(exclude_from_rollup_list)`):

```python
if "allowed_dpids" not in agg_config:
    raise ValueError(
        f"[agg.{agg_name}] missing required field 'allowed_dpids'. "
        f"Use [\"*\"] to include all data partners."
    )
allowed_dpids_raw = agg_config["allowed_dpids"]
if not isinstance(allowed_dpids_raw, list):
    raise ValueError(
        f"[agg.{agg_name}] allowed_dpids must be a list, "
        f"got {type(allowed_dpids_raw).__name__}"
    )
allowed_dpids = tuple(str(d).lower() for d in allowed_dpids_raw)
```

Then pass `allowed_dpids=allowed_dpids` to the `AggTypeConfig` constructor at line 151.

**Verification:**
Run: `pytest tests/test_config.py -x -q`
Expected: Existing tests that use inline TOML without `allowed_dpids` will now fail (specifically `test_load_valid_config`, `test_table_override_parsing`, `test_exclude_from_rollup_defaults_to_empty`, `test_dataclass_frozen`, `test_output_path_tilde_expansion`, `test_output_path_relative_preserved`, `test_example_config_loadable_ac6_2`). This is expected — Task 3 fixes them.

**Commit:** `feat(config): require allowed_dpids in TOML agg blocks`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Update example TOML, existing tests, and add new AC tests

**Verifies:** dpid-filtering.AC1.1, dpid-filtering.AC1.2, dpid-filtering.AC1.3, dpid-filtering.AC1.4, dpid-filtering.AC1.5

**Files:**
- Modify: `pyaggregate.example.toml:8-22`
- Modify: `tests/test_config.py`
- Test: `tests/test_config.py` (unit)

**Implementation:**

**Step 1: Update `pyaggregate.example.toml`**

Add `allowed_dpids` to each `[agg.<name>]` block. Use `["*"]` as the default to show the wildcard pattern. Add a comment about case sensitivity on the first occurrence:

```toml
[agg.qa]
source_reqtype = "qar"
output_path = "/data/outputs/qa"
# DPIDs are lowercase (matched against catalog path-derived values)
allowed_dpids = ["*"]
exclude_from_rollup = ["*_stats"]

[agg.qm]
source_reqtype = "qmr"
output_path = "/data/outputs/qm"
allowed_dpids = ["*"]
exclude_from_rollup = ["*_stats"]

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "/data/outputs/snapshot"
allowed_dpids = ["*"]
exclude_from_rollup = []
```

**Step 2: Update existing test TOML strings in `tests/test_config.py`**

Add `allowed_dpids = ["*"]` to every inline TOML string that defines an `[agg.<name>]` block. This affects the following tests:
- `test_load_valid_config` (lines 24-47) — 3 agg blocks
- `test_table_override_parsing` (lines 112-127) — 1 agg block
- `test_exclude_from_rollup_defaults_to_empty` (lines 142-153) — 1 agg block
- `test_dataclass_frozen` (lines 164-175) — 1 agg block
- `test_output_path_tilde_expansion` (lines 230-241) — 1 agg block
- `test_output_path_relative_preserved` (lines 250-261) — 1 agg block

Tests that validate error paths (`test_missing_scan_section`, `test_missing_requests_root`, `test_legacy_output_section_rejected`, `test_missing_output_path_rejected`, `test_output_path_non_string_rejected`) do NOT need `allowed_dpids` because they fail before reaching that validation.

**Step 3: Update `test_load_valid_config` assertions**

Add assertion for `allowed_dpids` parsing in the qa config verification block (after line 74):

```python
assert qa_config.allowed_dpids == ("*",)
```

**Step 4: Add new tests for dpid-filtering.AC1 acceptance criteria**

Add these tests to the `TestLoadConfig` class:

Tests must verify each AC listed:
- **dpid-filtering.AC1.1:** Config with `allowed_dpids = ["msoc", "nsdp"]` parses into `tuple[str, ...]` with correct values
- **dpid-filtering.AC1.2:** Config with `allowed_dpids = ["*"]` parses without error and produces `("*",)`
- **dpid-filtering.AC1.3:** Config with `allowed_dpids = []` parses without error and produces `()`
- **dpid-filtering.AC1.4:** Config missing `allowed_dpids` entirely raises `ValueError` with message mentioning `allowed_dpids`
- **dpid-filtering.AC1.5:** Config with `allowed_dpids = "not_a_list"` (string instead of list) raises `ValueError` with message mentioning `allowed_dpids`
- **Case normalization:** Config with `allowed_dpids = ["MSOC", "NsDp"]` parses into `("msoc", "nsdp")` — verifies the `.lower()` normalization in Task 2's parsing code guards against mixed-case input

Follow the existing test patterns: inline TOML via `tmp_path`, `pytest.raises` with `match` for error cases, direct assertion on parsed config for success cases.

**Verification:**
Run: `pytest tests/test_config.py -v`
Expected: All existing tests pass (with updated TOML), all new AC1 tests pass.

Run: `ruff check src/pyaggregate/config.py tests/test_config.py`
Expected: No lint errors.

Run: `mypy src/pyaggregate/config.py`
Expected: No type errors.

**Commit:** `feat(config): add allowed_dpids tests and update example TOML`
<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_A -->
