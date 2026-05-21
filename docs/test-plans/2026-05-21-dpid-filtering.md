# Human Test Plan: Per-Agg-Type DPID Filtering

## Prerequisites

- Python 3.11+ environment with pyaggregate installed (`pip install -e .`)
- All automated tests passing: `pytest` (exit code 0)
- Access to a requests tree with at least 2 distinct DPIDs (e.g., `aeos` and `cms`)
- A working `pyaggregate.toml` config file

## Phase 1: Scanner Independence (dpid-filtering.AC5.1)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Run `pytest tests/test_scanner.py tests/test_scanner_concurrency.py -v` | All tests pass without modification from the DPID filtering feature branch |
| 2 | Run `grep -r filter_allowed_dpids src/pyaggregate/io/scanner.py` | No output (scanner has no reference to the DPID filtering function) |
| 3 | Run `grep -r "from pyaggregate.core.input_resolution" src/pyaggregate/io/scanner.py` | No output (scanner does not import from input_resolution) |
| 4 | Create config with `allowed_dpids = ["aeos"]` for `[agg.qa]`. Run `pyaggregate scan --config <path>` against a requests tree containing `aeos`, `cms`, and `kpsc` directories. | Scan completes successfully. Run `pyaggregate show-catalog --config <path>` and confirm all three DPIDs (`aeos`, `cms`, `kpsc`) are present in the catalog. The `allowed_dpids` restriction did not affect scan behaviour. |

## Phase 2: DPID Filtering in Run

| Step | Action | Expected |
|------|--------|----------|
| 5 | Set `allowed_dpids = ["aeos"]` in `[agg.qa]` config. Run `pyaggregate run --type qa --config <path>`. | Output directory contains only `aeos` data. Open `stacked/*.parquet` files and confirm the `dpid` column contains only `"aeos"`. No `cms` or other DPIDs present. |
| 6 | Set `allowed_dpids = ["*"]` in `[agg.qa]` config. Run `pyaggregate run --type qa --force --config <path>`. | Output contains all DPIDs from the catalog. Open `stacked/*.parquet` and confirm all expected DPIDs are present. |
| 7 | Set `allowed_dpids = []` in `[agg.qa]` config. Run `pyaggregate run --type qa --force --config <path>`. | Run completes (exit code 0 or appropriate empty-run behaviour). No parquet files are written to the stacked directory, or the run reports zero tables processed. |
| 8 | Set `allowed_dpids = ["aeos", "nonexistent_dp"]` in `[agg.qa]` config. Run `pyaggregate run --type qa --force --config <path>`. | Run completes successfully (exit 0). Terminal/log output includes a WARNING mentioning `"nonexistent_dp"` and `"not found in the catalog"`. Output contains only `aeos` data. |

## Phase 3: Config Validation Edge Cases

| Step | Action | Expected |
|------|--------|----------|
| 9 | Remove the `allowed_dpids` line entirely from an `[agg.qa]` block. Run `pyaggregate run --config <path>`. | CLI exits with non-zero exit code. Error message mentions `allowed_dpids`. |
| 10 | Set `allowed_dpids = "aeos"` (string, not list). Run `pyaggregate run --config <path>`. | CLI exits with non-zero exit code. Error message mentions `allowed_dpids` must be a list. |
| 11 | Set `allowed_dpids = ["AEOS", "CMS"]` (uppercase). Run `pyaggregate run --type qa --config <path>`. | Run succeeds. Output contains `aeos` and `cms` data (case-insensitive matching works). |

## Phase 4: Per-Agg-Type Independence

| Step | Action | Expected |
|------|--------|----------|
| 12 | Set `allowed_dpids = ["aeos"]` for `[agg.qa]` and `allowed_dpids = ["cms"]` for `[agg.qm]` and `allowed_dpids = ["*"]` for `[agg.snapshot]`. Run `pyaggregate run --config <path>`. | QA output contains only `aeos`. QM output contains only `cms`. Snapshot output contains all DPIDs with `has_scdm=1`. Each agg type respects its own allowlist independently. |

## End-to-End: Full Pipeline With DPID Filtering

| Step | Action | Expected |
|------|--------|----------|
| 13 | Start with a clean state directory. Run `pyaggregate init-db --config <path>`. | Catalog DB created successfully. |
| 14 | Run `pyaggregate scan --config <path>` with a requests tree containing `aeos`, `cms`, `kpsc`. | All three DPIDs catalogued (verify with `show-catalog`). |
| 15 | Config has `allowed_dpids = ["aeos", "kpsc"]` for `[agg.qa]`. Run `pyaggregate run --type qa --config <path>`. | Run exits 0. Output contains only `aeos` and `kpsc` data. `dpid_map.csv` contains only surrogates for `aeos` and `kpsc`. `masked/*.parquet` files reference only those surrogates. `cms` is completely absent from all outputs. |
| 16 | Run `pyaggregate run --type qa --run-id recheck --force --config <path>` after changing `allowed_dpids = ["*"]`. | New run directory `recheck/` appears. All three DPIDs now present in output. `dpid_map.csv` updated to include `cms` surrogate. Previous run directory is untouched. |

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| dpid-filtering.AC1.1 | `test_config.py::test_allowed_dpids_list_parsing_ac1_1` | Step 5 |
| dpid-filtering.AC1.2 | `test_config.py::test_allowed_dpids_wildcard_ac1_2` | Step 6 |
| dpid-filtering.AC1.3 | `test_config.py::test_allowed_dpids_empty_list_ac1_3` | Step 7 |
| dpid-filtering.AC1.4 | `test_config.py::test_allowed_dpids_missing_raises_ac1_4` | Step 9 |
| dpid-filtering.AC1.5 | `test_config.py::test_allowed_dpids_non_list_raises_ac1_5` | Step 10 |
| dpid-filtering.AC1 (case) | `test_config.py::test_allowed_dpids_case_normalization` | Step 11 |
| dpid-filtering.AC2.1 | `test_input_resolution.py::test_filter_specific_dpids_returns_matching_rows` | Step 5 |
| dpid-filtering.AC2.2 | `test_input_resolution.py::test_filter_wildcard_returns_all_rows` | Step 6 |
| dpid-filtering.AC2.3 | `test_input_resolution.py::test_filter_empty_list_returns_empty_dataframe` | Step 7 |
| dpid-filtering.AC2.4 | `test_input_resolution.py::test_filter_preserves_all_columns` | -- |
| dpid-filtering.AC2.5 | `test_input_resolution.py::test_filter_unknown_dpid_no_error` | Step 8 |
| dpid-filtering.AC3.1 | `test_input_resolution.py::test_check_unknown_dpids_warns_for_missing_dpid` | Step 8 |
| dpid-filtering.AC3.2 | `test_input_resolution.py::test_check_unknown_dpids_wildcard_no_warnings` | Step 6 |
| dpid-filtering.AC3.3 | `test_input_resolution.py::test_check_unknown_dpids_all_found_no_warnings` | -- |
| dpid-filtering.AC4.1 | `test_input_resolution.py::test_resolve_inputs_applies_allowed_dpids_filter` | Step 15 |
| dpid-filtering.AC4.2 | `test_run_orchestration.py::test_run_logs_unknown_dpid_warning_ac4_2` | Step 8 |
| dpid-filtering.AC4.3 | `test_input_resolution.py::test_resolve_inputs_applies_allowed_dpids_filter` | Step 15 |
| dpid-filtering.AC5.1 | -- (architectural boundary) | Steps 1-4 |
