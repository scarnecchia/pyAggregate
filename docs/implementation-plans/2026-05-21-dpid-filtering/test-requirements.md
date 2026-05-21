# Test Requirements: Per-Agg-Type DPID Filtering

## Automated Test Coverage

| Acceptance Criterion | Test Type | Test File | Test Description |
|---|---|---|---|
| dpid-filtering.AC1.1 | unit | tests/test_config.py | Config with `allowed_dpids = ["msoc", "nsdp"]` parses into `tuple[str, ...]` with correct values `("msoc", "nsdp")` |
| dpid-filtering.AC1.2 | unit | tests/test_config.py | Config with `allowed_dpids = ["*"]` parses without error and produces `("*",)` |
| dpid-filtering.AC1.3 | unit | tests/test_config.py | Config with `allowed_dpids = []` parses without error and produces `()` |
| dpid-filtering.AC1.4 | unit | tests/test_config.py | Config missing `allowed_dpids` entirely raises `ValueError` with message mentioning `allowed_dpids` |
| dpid-filtering.AC1.5 | unit | tests/test_config.py | Config with `allowed_dpids = "not_a_list"` (string instead of list) raises `ValueError` mentioning `allowed_dpids` |
| dpid-filtering.AC1 (case normalization) | unit | tests/test_config.py | Config with `allowed_dpids = ["MSOC", "NsDp"]` parses into `("msoc", "nsdp")` -- verifies `.lower()` normalization guards against mixed-case input |
| dpid-filtering.AC2.1 | unit | tests/test_input_resolution.py | Catalog with dpids `["aeos", "cms", "nsdp"]` filtered with `allowed_dpids=("aeos", "cms")` returns only `aeos` and `cms` rows |
| dpid-filtering.AC2.2 | unit | tests/test_input_resolution.py | Catalog filtered with `allowed_dpids=("*",)` returns all rows unchanged (same height as input) |
| dpid-filtering.AC2.3 | unit | tests/test_input_resolution.py | Catalog filtered with `allowed_dpids=()` returns empty DataFrame |
| dpid-filtering.AC2.4 | unit | tests/test_input_resolution.py | Filtered result preserves all original columns (`set(result.columns) == set(catalog.columns)`) |
| dpid-filtering.AC2.5 | unit | tests/test_input_resolution.py | Catalog with dpids `["aeos", "cms"]` filtered with `allowed_dpids=("aeos", "unknown_dp")` returns only `aeos` rows -- no error for missing DPID |
| dpid-filtering.AC3.1 | unit | tests/test_input_resolution.py | `check_unknown_dpids(("aeos", "unknown_dp"), {"aeos", "cms"})` returns one warning string mentioning `"unknown_dp"` |
| dpid-filtering.AC3.2 | unit | tests/test_input_resolution.py | `check_unknown_dpids(("*",), {"aeos", "cms"})` returns empty list (wildcard skips check) |
| dpid-filtering.AC3.3 | unit | tests/test_input_resolution.py | `check_unknown_dpids(("aeos", "cms"), {"aeos", "cms"})` returns empty list (all found) |
| dpid-filtering.AC4.1 | integration | tests/test_input_resolution.py | `resolve_inputs` with two-DP catalog and `allowed_dpids=("aeos",)` returns only `aeos` inputs -- DPID filter applied between `filter_catalog` and `select_latest_workplan_per_dp` |
| dpid-filtering.AC4.2 | integration | tests/test_run_orchestration.py or tests/test_e2e_smoke.py | CLI run command with an unknown DPID in `allowed_dpids` emits a structured warning log via `pyaggregate.run.inputs` logger with `run_id` and `agg_type` extra fields |
| dpid-filtering.AC4.3 | integration | tests/test_input_resolution.py | `resolve_inputs` result naturally excludes filtered-out DPs -- if `cms` is filtered out, its tables do not appear in the output dict, with no downstream code changes required |

## Human Verification Required

| Acceptance Criterion | Justification | Verification Approach |
|---|---|---|
| dpid-filtering.AC5.1 | Verified by architectural boundary rather than explicit assertion. The scanner (`io/scanner.py`) has no import path to `filter_allowed_dpids` (`core/input_resolution.py`), and `filter_allowed_dpids` is only called from `io/input_resolver.py`. Existing scanner tests (`test_scanner.py`, `test_scanner_concurrency.py`) remain unmodified and passing, confirming scan behaviour is unchanged. | 1. Confirm `test_scanner.py` and `test_scanner_concurrency.py` pass without modification after all three phases are implemented. 2. Verify via `grep -r filter_allowed_dpids src/pyaggregate/io/scanner.py` that the scanner has no reference to the new filtering function. 3. Run a full scan against a test catalog and confirm all DPs are catalogued regardless of `allowed_dpids` config values. |
