# Rework Output Config — Phase 4: E2E Smoke and Integration Verification

**Goal:** End-to-end smoke tests pass against the new per-agg `output_path` schema and `snapshot` identifier. Helper functions updated to accept per-agg output paths. Full test suite green.

**Architecture:** Update E2E smoke test TOML fixtures to use per-agg `output_path` instead of global `[output]`. Update helper verification functions to accept a dict of `{agg_type: output_path}` instead of a single `output_dir`. Update the pyaggregate.toml example config to reflect the final schema (AC6.2).

**Tech Stack:** Python 3.12+, pytest, typer, polars

**Scope:** 4 phases from original design (phase 4 of 4)

**Codebase verified:** 2026-05-20

---

## Acceptance Criteria Coverage

This phase implements and tests:

### rework-output-config.AC1: Per-agg output_path is honoured (integration-level)

- **rework-output-config.AC1.1 Success:** Given a config where `[agg.snapshot]` declares `output_path = "/tmp/foo/snapshot"`, running pyaggregate writes table parquet files to `/tmp/foo/snapshot/{run_id}/{stacked,masked,rollup}/<table>.parquet`.
- **rework-output-config.AC1.2 Success:** A single config invocation that runs multiple agg types (e.g., `--type snapshot --type qa --type qm`) writes each agg's outputs to its own configured `output_path` — the three trees do not share a common parent in the path layout.

### rework-output-config.AC2: Writer signature and path composition (integration-level)

- **rework-output-config.AC2.1 Success:** `write_run(output_path, agg_type, run_id, ...)` writes `dpid_map.csv` and `run_summary.json` at `{output_path}/{run_id}/`.

### rework-output-config.AC3: latest symlink (integration-level)

- **rework-output-config.AC3.1 Success:** When `update_latest=True`, the writer creates a symlink at `{output_path}/latest` pointing to the relative path `{run_id}`.

### rework-output-config.AC6: Cross-cutting

- **rework-output-config.AC6.1 Success:** The full `pytest` suite passes with the refactor in place; no test still references `OutputConfig`, `output_root`, `--output-root`, or `sdd` as an agg-type identifier.
- **rework-output-config.AC6.2 Success:** `pyaggregate.toml` (the root example config) reflects the new schema and is loadable by `load_config()` without modification.

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Update E2E smoke test TOML fixtures and helper functions

**Verifies:** rework-output-config.AC1.1 (integration), rework-output-config.AC2.1 (integration), rework-output-config.AC3.1 (integration)

**Files:**
- Modify: `tests/test_e2e_smoke.py:100-124` (TOML fixture in `test_full_pipeline_ac9_1`)
- Modify: `tests/test_e2e_smoke.py:184-208` (TOML fixture in `test_full_pipeline_ac9_2_rerun_with_force`)
- Modify: `tests/test_e2e_smoke.py:138-152` (verification calls in `test_full_pipeline_ac9_1`)
- Modify: `tests/test_e2e_smoke.py:248-254` (verification calls in `test_full_pipeline_ac9_2_rerun_with_force`)
- Modify: `tests/test_e2e_smoke.py:260-300` (`_verify_output_files_exist` helper)
- Modify: `tests/test_e2e_smoke.py:302-363` (`_verify_row_count_consistency` helper)
- Modify: `tests/test_e2e_smoke.py:365-406` (`_verify_dpid_map_valid` helper)
- Modify: `tests/test_e2e_smoke.py:408-428` (`_verify_latest_symlinks` helper)
- Modify: `tests/test_e2e_smoke.py:430-460` (`_capture_output_row_counts` helper)

**Implementation:**

The E2E tests currently use a single `output_dir` and construct paths as `output_dir / agg_type / ...`. After the rework, each agg type has its own `output_path` and the `agg_type` segment is gone from path composition. The helpers need to accept per-agg output paths.

**1. Update TOML fixtures (both tests):**

Replace the `[output]` section with per-agg `output_path` in both test fixtures. Use `output_dir / agg_type` as each agg's output_path so the filesystem layout mirrors the old structure (different roots per agg):

```python
config_path.write_text(f"""
[scan]
requests_root = "{requests_root}"

[state]
catalog_db = "{state_dir / "catalog.db"}"
log_dir = "{state_dir / "logs"}"

[agg.qa]
source_reqtype = "qar"
output_path = "{output_dir / "qa"}"
exclude_from_rollup = []

[agg.qm]
source_reqtype = "qmr"
output_path = "{output_dir / "qm"}"
exclude_from_rollup = []

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "{output_dir / "snapshot"}"
exclude_from_rollup = []
""")
```

Note: `[agg.sdd]` → `[agg.snapshot]` per Phase 3.

**2. Build per-agg output paths dict in each test:**

After creating the config, build a mapping for the verification helpers:

```python
agg_output_paths = {
    "qa": output_dir / "qa",
    "qm": output_dir / "qm",
    "snapshot": output_dir / "snapshot",
}
```

Pass this dict to all verification helpers instead of the bare `output_dir`.

**3. Update verification helper signatures and internals:**

All five helper functions follow the same pattern — they loop over agg types and construct `output_dir / agg_type` as the base. Change them to accept the paths dict and use the values directly:

**`_verify_output_files_exist(agg_output_paths: dict[str, Path], run_id: str = "latest")`:**
- Loop: `for agg_type, agg_output_path in agg_output_paths.items():`
- Remove: `agg_dir = output_dir / agg_type`
- Use `agg_output_path` directly as the agg root
- Symlink check: `latest_dir = agg_output_path / "latest"` (was `agg_dir / "latest"`)
- Run base: `run_base = agg_output_path / run_id` (was `agg_dir / run_id`)

**`_verify_row_count_consistency(agg_output_paths: dict[str, Path], run_id: str = "latest")`:**
- Same pattern: iterate dict, use `agg_output_path` instead of `output_dir / agg_type`

**`_verify_dpid_map_valid(agg_output_paths: dict[str, Path], run_id: str = "latest")`:**
- Same pattern

**`_verify_latest_symlinks(agg_output_paths: dict[str, Path])`:**
- Same pattern: `latest_link = agg_output_path / "latest"`

**`_capture_output_row_counts(agg_output_paths: dict[str, Path], run_id: str)`:**
- Same pattern: `run_base = agg_output_path / run_id`

**4. Update test method verification calls:**

In `test_full_pipeline_ac9_1`:
```python
_verify_output_files_exist(agg_output_paths)
_verify_row_count_consistency(agg_output_paths)
_verify_dpid_map_valid(agg_output_paths)
_verify_latest_symlinks(agg_output_paths)
```

In `test_full_pipeline_ac9_2_rerun_with_force`:
```python
_verify_output_files_exist(agg_output_paths, run_id)
_verify_row_count_consistency(agg_output_paths, run_id)
_verify_dpid_map_valid(agg_output_paths, run_id)
first_run_outputs = _capture_output_row_counts(agg_output_paths, run_id)
second_run_outputs = _capture_output_row_counts(agg_output_paths, run_id)
```

**5. Add AC1.2 explicit verification in `test_full_pipeline_ac9_1`:**

After the verification helper calls, add an explicit assertion that the three output paths are distinct and non-overlapping (AC1.2):

```python
# AC1.2: Verify each agg type wrote to its own independent output_path
for agg_type, agg_output_path in agg_output_paths.items():
    assert agg_output_path.exists(), f"{agg_type} output_path missing: {agg_output_path}"

# Assert no common parent beyond output_dir itself
output_parents = {p.parent for p in agg_output_paths.values()}
assert len(output_parents) == 1, "Agg output paths should share only one common parent"
assert output_parents.pop() == output_dir, "Common parent should be the base output_dir"
```

**Testing:**
- rework-output-config.AC1.1 (integration): `test_full_pipeline_ac9_1` verifies snapshot output at `output_dir/snapshot/{run_id}/stacked/`
- rework-output-config.AC1.2 (integration): Explicit assertion that all three agg output paths are distinct directories under `output_dir`
- rework-output-config.AC2.1 (integration): helpers verify `dpid_map.csv` and `run_summary.json` at `{output_path}/{run_id}/`
- rework-output-config.AC3.1 (integration): `_verify_latest_symlinks` checks `{output_path}/latest`

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest tests/test_e2e_smoke.py -v -m integration`
Expected: All 3 tests pass

**Commit:** `test: update E2E smoke tests for per-agg output_path and snapshot rename`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Verify pyaggregate.toml example config (AC6.2)

**Verifies:** rework-output-config.AC6.2

**Files:**
- Verify: `pyaggregate.toml` (should already be updated from Phase 1 Task 3 + Phase 3 Task 3)

**Implementation:**

Verify that the root `pyaggregate.toml` reflects the final schema with `[agg.snapshot]` (not `[agg.sdd]`) and per-agg `output_path` (no `[output]` section). This should already be correct after Phase 1 created it and Phase 3 renamed sdd → snapshot.

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -c "from pyaggregate.config import load_config; from pathlib import Path; c = load_config(Path('pyaggregate.toml')); print(list(c.agg_types.keys())); print(c.agg_types['snapshot'].output_path)"`
Expected: `['qa', 'qm', 'snapshot']` and the configured output_path

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -c "\[output\]" pyaggregate.toml`
Expected: `0` (no `[output]` section)

**Commit:** No commit — verification only. If issues found, fix and commit: `fix: correct pyaggregate.toml example config`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Full test suite and dead reference sweep (AC6.1)

**Verifies:** rework-output-config.AC6.1

**Files:** None (verification and cleanup only)

**Implementation:**

Run the complete test suite and perform a dead reference sweep to ensure nothing still references `OutputConfig`, `output_root` as a config field, `--output-root`, or `sdd` as an agg-type identifier.

**Verification:**

Step 1 — Full test suite:
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest -v`
Expected: All tests pass (0 failures)

Step 2 — Dead reference sweep:
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn "OutputConfig" src/ tests/ --include="*.py"`
Expected: No matches

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn "output_root" src/ tests/ --include="*.py" | grep -v "# .*output_root\|migration"`
Expected: No matches (except possibly in test_config.py's legacy rejection test which validates the migration message text)

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn "\-\-output-root" src/ tests/ --include="*.py"`
Expected: No matches

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn "\"sdd\"\|'sdd'\|\[agg\.sdd\]" src/ tests/ pyaggregate.toml --include="*.py" --include="*.toml"`
Expected: No matches

Step 3 — Type check:
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m mypy src/pyaggregate/ --ignore-missing-imports`
Expected: No errors (or same errors as before the rework — no new type errors introduced)

**Commit:** No commit if clean. If issues found, fix and commit: `fix: remove remaining dead references from rework`

<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->
