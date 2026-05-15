# Human Test Plan: pyAggregate Unified QA/QM/SDD

## Overview

This test plan covers manual verification steps for pyaggregate after automated tests pass. Focus areas: real SAS file handling, operational workflows, and edge cases that synthetic fixtures cannot fully exercise.

## Prerequisites

- pyaggregate installed (`pip install -e ".[dev]"`)
- Access to a `requests/` tree with real SAS files (at least 3 DPs across qa and qm)
- A writable output directory
- Python 3.11+

## Test Scenarios

### 1. Fresh Install and CLI Verification

- [ ] `pip install -e .` succeeds without errors
- [ ] `pyaggregate --help` exits 0 and lists: scan, run, init-db, show-catalog, show-dpid-map, show-scans
- [ ] `pyaggregate --version` shows 0.1.0 (if version flag added)
- [ ] `pyaggregate scan --help` shows --config and --dry-run flags
- [ ] `pyaggregate run --help` shows all flags: --type, --catalog, --output-root, --run-id, --update-latest/--no-update-latest, --force, --config

### 2. Init-DB and Catalog Operations

- [ ] `pyaggregate init-db --config pyaggregate.toml` creates catalog.db
- [ ] `pyaggregate show-catalog` shows empty catalog
- [ ] `pyaggregate show-dpid-map` shows empty mapping
- [ ] `pyaggregate show-scans` shows empty scan log

### 3. Scanner with Real Data

- [ ] `pyaggregate scan --config pyaggregate.toml` completes without error
- [ ] `pyaggregate show-catalog` shows expected rows with correct dpid, wpid, reqtype, verid
- [ ] Verify highest verid is selected when multiple versions exist
- [ ] Verify `has_scdm=1` for DPs with `scdm_snapshot/` directories
- [ ] `pyaggregate scan --dry-run` reports intended changes without modifying DB
- [ ] Running scan twice shows "no changes" or only updated `observed_at`
- [ ] `pyaggregate show-scans` shows scan log entries with timestamps

### 4. Concurrent Scan Guard

- [ ] Start a long-running scan (or hold the lock manually via `flock`)
- [ ] Attempt a second `pyaggregate scan` — should exit 0 with "scan already in progress"

### 5. Aggregation Run with Real SAS Files

- [ ] `pyaggregate run --config pyaggregate.toml` produces output directories
- [ ] Verify directory structure: `outputs/{qa,qm,sdd}/<date>/stacked/`, `masked/`, `rollup/`
- [ ] Open stacked parquet files — verify `dpid` column present with real DP names
- [ ] Open masked parquet files — verify `surrogate_id` column, NO `dpid` column
- [ ] Verify masked row count equals stacked row count per table
- [ ] Verify rollup row count <= stacked row count per table
- [ ] Verify `dpid_map.csv` contains only surrogates present in masked outputs
- [ ] Verify `run_summary.json` has correct structure and table counts
- [ ] Verify `latest` symlink resolves to the run directory
- [ ] No `.tmp` files in the output tree

### 6. Type Filtering

- [ ] `pyaggregate run --type qa` produces only qa/ output, no qm/ or sdd/
- [ ] `pyaggregate run --type qa --type sdd` produces qa/ and sdd/ only

### 7. Alternate Paths

- [ ] `pyaggregate run --catalog /tmp/alt.db` uses alternate catalog
- [ ] `pyaggregate run --output-root /tmp/alt-out` writes to alternate location
- [ ] Default output_root is NOT modified when using alternate

### 8. Run ID and Force

- [ ] `pyaggregate run --run-id 2026-05-14-manual` creates directory with that name
- [ ] Running again with same `--run-id` without `--force` fails with "already exists"
- [ ] Running with `--run-id 2026-05-14-manual --force` overwrites cleanly
- [ ] `--run-id X --no-update-latest` creates output but doesn't move `latest` symlink

### 9. Partial Failure Handling

- [ ] If a SAS file is corrupted/missing, the run logs a warning and continues with other tables
- [ ] Exit code is 2 for partial success (some tables failed)
- [ ] `run_summary.json` lists skipped tables with error classification

### 10. Logging

- [ ] With `--verbose`, DEBUG-level logs appear on stderr
- [ ] Log file created at `log_dir/pyaggregate-YYYY-MM-DD.log`
- [ ] Log entries are valid JSON (one per line)
- [ ] `jq . < pyaggregate-YYYY-MM-DD.log` parses successfully

### 11. SDD Aggregation

- [ ] SDD output includes data from both qar and qmr scdm_snapshot directories
- [ ] DP with only qar scdm_snapshot (no qmr) contributes without error
- [ ] File collision warnings logged when same filename exists in both qar and qmr

### 12. Stats Exclusion

- [ ] Tables matching `*_stats` pattern have stacked + masked but NO rollup
- [ ] Non-matching tables have all three outputs (stacked, masked, rollup)

## Sign-off

| Tester | Date | Result | Notes |
|--------|------|--------|-------|
| | | | |
