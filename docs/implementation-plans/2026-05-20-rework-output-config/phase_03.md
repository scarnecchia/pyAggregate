# Rework Output Config — Phase 3: sdd to snapshot rename

**Goal:** The agg_type identifier `sdd` is renamed to `snapshot` everywhere — config keys, CLI argument values, function names, docstrings, fixtures, examples, and documentation. "SCDM" the proper noun stays. `has_scdm` (catalog column) and `scdm_snapshot` (filesystem directory) stay.

**Architecture:** Hard rename with no migration shim. Grep-driven mechanical replacement of the `sdd` agg-type identifier. Preserve all SCDM proper noun references, `has_scdm` catalog column, and `scdm_snapshot` directory name.

**Tech Stack:** Python 3.12+, pytest

**Scope:** 4 phases from original design (phase 3 of 4)

**Codebase verified:** 2026-05-20

---

## Acceptance Criteria Coverage

This phase implements and tests:

### rework-output-config.AC5: sdd to snapshot rename

- **rework-output-config.AC5.1 Success:** CLI invocation with `--type snapshot` selects the snapshot agg type and runs the same aggregation logic that `--type sdd` previously selected.
- **rework-output-config.AC5.2 Failure:** CLI invocation with `--type sdd` against a config that declares `[agg.snapshot]` (and no `[agg.sdd]`) exits non-zero with an "unknown agg type" error listing the configured types.
- **rework-output-config.AC5.3 Success:** `detect_snapshot_collisions()` (renamed from `detect_sdd_collisions`) is importable from `src/pyaggregate/core/input_resolution.py` and produces the same collision-detection behaviour for snapshot-type input resolution.

---

## Rename Inventory

The codebase investigator identified all occurrences. This is the exhaustive list of changes, categorized by action:

**RENAME** (change `sdd` → `snapshot` as agg-type identifier):
- Source: writer.py docstrings (3 lines), input_resolver.py docstring (1 line), input_resolution.py function name + docstring (2 lines), cli.py (0 — "SCDM Snapshot" is preserved)
- Config: pyaggregate.toml `[agg.sdd]` → `[agg.snapshot]`
- Tests: test_config.py (5 lines), test_e2e_smoke.py (8 lines), test_input_resolution.py (10 lines), test_run_orchestration.py (8 lines)
- Docs: operations.md (4 lines), migration.md (3 lines)

**PRESERVE** (do NOT change):
- `has_scdm` — database column and catalog field (50+ refs across catalog_store, scanner, test fixtures)
- `scdm_snapshot` — filesystem directory name (15+ refs)
- `SCDM` / `SCDM Snapshot` — proper noun (cli.py line 16, 56)
- `glob_scdm_tables` — function name referencing SCDM directory, not the agg identifier
- All refs in `docs/design-plans/` — historical records

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Rename detect_sdd_collisions and update source docstrings

**Verifies:** rework-output-config.AC5.3

**Files:**
- Modify: `src/pyaggregate/core/input_resolution.py:42` (docstring: "sdd type" → "snapshot type")
- Modify: `src/pyaggregate/core/input_resolution.py:125` (function name: `detect_sdd_collisions` → `detect_snapshot_collisions`)
- Modify: `src/pyaggregate/core/input_resolution.py:126` (docstring: "SDD inputs" → "snapshot inputs")
- Modify: `src/pyaggregate/io/input_resolver.py:27` (docstring: "For sdd:" → "For snapshot:")
- Modify: `src/pyaggregate/io/writer.py:34` (docstring: "qa, qm, sdd" → "qa, qm, snapshot")
- Modify: `src/pyaggregate/io/writer.py:190` (docstring: "qa, qm, sdd" → "qa, qm, snapshot")
- Modify: `src/pyaggregate/io/writer.py:216` (docstring: "qa, qm, sdd" → "qa, qm, snapshot")

**Implementation:**

Mechanical find-and-replace in source files only:

1. `input_resolution.py:42`: Change `For sdd type:` → `For snapshot type:`
2. `input_resolution.py:125`: Rename function `detect_sdd_collisions` → `detect_snapshot_collisions`
3. `input_resolution.py:126`: Change docstring `Detect filename collisions in SDD inputs` → `Detect filename collisions in snapshot inputs`
4. `input_resolver.py:27`: Change `For sdd:` → `For snapshot:`
5. `writer.py` lines 34, 190, 216: Change `(qa, qm, sdd)` → `(qa, qm, snapshot)` in all three docstrings

Do NOT change:
- `glob_scdm_tables` in input_resolver.py — refers to `scdm_snapshot` directory
- `has_scdm` anywhere
- `scdm_snapshot` directory references
- "SCDM Snapshot" in cli.py lines 16, 56

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -c "from pyaggregate.core.input_resolution import detect_snapshot_collisions; print('import OK')"`
Expected: `import OK`

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn "detect_sdd_collisions\|agg_type.*sdd\|qa, qm, sdd" src/ --include="*.py"`
Expected: No matches

**Commit:** `refactor: rename sdd to snapshot in source code identifiers and docstrings`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update test files for sdd → snapshot rename

**Verifies:** rework-output-config.AC5.1, rework-output-config.AC5.2, rework-output-config.AC5.3

**Files:**
- Modify: `tests/test_config.py` (lines 44, 72, 80-84)
- Modify: `tests/test_input_resolution.py` (lines 13, 92, 95, 98, 318, 329, 344, 357, 363, 407, 427)
- Modify: `tests/test_run_orchestration.py` (lines 70, 95, 186, 191, 199, 205, 215, 227-229, 432)
- Modify: `tests/test_e2e_smoke.py` (lines 57, 120, 204, 267, 313, 372, 414, 442)

**Implementation:**

**test_config.py:**
- Line 44: `[agg.sdd]` → `[agg.snapshot]`
- Line 72: `assert "sdd" in config.agg_types` → `assert "snapshot" in config.agg_types`
- Line 80: `# Verify sdd config` → `# Verify snapshot config`
- Line 81: `sdd_config = config.agg_types["sdd"]` → `snapshot_config = config.agg_types["snapshot"]`
- Line 82: `assert sdd_config.name == "sdd"` → `assert snapshot_config.name == "snapshot"`
- Lines 83-84: Update variable name from `sdd_config` to `snapshot_config` (values `has_scdm` and `scdm_snapshot` stay)

**test_input_resolution.py:**
- Line 13: `detect_sdd_collisions` → `detect_snapshot_collisions` (import)
- Line 92: `test_filter_catalog_sdd_config_filters_has_scdm` → `test_filter_catalog_snapshot_config_filters_has_scdm` (function name)
- Line 95: `"""SDD config filters to source_field='has_scdm' == 1."""` → `"""Snapshot config filters to source_field='has_scdm' == 1."""`
- Line 98: `name="sdd"` → `name="snapshot"` (AggTypeConfig constructor)
- Line 318: `detect_sdd_collisions` → `detect_snapshot_collisions` (docstring)
- Lines 329, 344, 357, 363: `detect_sdd_collisions(...)` → `detect_snapshot_collisions(...)` (function calls)
- Line 407: `test_resolve_inputs_sdd_with_subdirectory` → `test_resolve_inputs_snapshot_with_subdirectory` (function name)
- Line 427: `name="sdd"` → `name="snapshot"` (AggTypeConfig constructor)

**test_run_orchestration.py:**
- Line 70: `"sdd": AggTypeConfig(name="sdd",` → `"snapshot": AggTypeConfig(name="snapshot",` (dict key and name param)
- Line 95: `[agg.sdd]` → `[agg.snapshot]` (TOML fixture)
- Line 176: `mock_glob_sdd_input` variable name → `mock_glob_scdm` (rename to match the underlying function being mocked: `glob_scdm_tables`). Do NOT rename to `mock_glob_snapshot_input` — the mock targets the SCDM directory glob function, not the agg-type identifier.
- Line 186: `mock_glob_sdd_input.return_value` → `mock_glob_scdm.return_value`
- Line 191: `"glob_sdd": mock_glob_sdd_input` → `"glob_scdm": mock_glob_scdm` (dict key matches the mocked function's domain, not the agg type)
- Line 199: `test_run_with_type_filter_qa_sdd_only` → `test_run_with_type_filter_qa_snapshot_only` (function name)
- Line 205: `--type sdd` → `--type snapshot` (docstring)
- Line 215: `"sdd"` → `"snapshot"` (CLI arg)
- Lines 227-229: `sdd_output` → `snapshot_output` (variable name), `"sdd"` → `"snapshot"` (path segment — note: after Phase 2, this references `config.agg_types["snapshot"].output_path`)
- Line 432: `["qa", "qm", "sdd"]` → `["qa", "qm", "snapshot"]` (loop)

**test_e2e_smoke.py:**
- Line 57: `qa, qm, sdd` → `qa, qm, snapshot` (comment)
- Lines 120, 204: `[agg.sdd]` → `[agg.snapshot]` (TOML fixtures)
- Lines 267, 313, 372, 414, 442: `["qa", "qm", "sdd"]` → `["qa", "qm", "snapshot"]` (loop iterations)

**Testing:**
- rework-output-config.AC5.1: Covered by test_run_orchestration tests that use `--type snapshot`
- rework-output-config.AC5.2: Covered by existing `test_run_unknown_type` logic (typer error on unknown type) — `--type sdd` is now unknown since config declares `[agg.snapshot]`
- rework-output-config.AC5.3: `test_input_resolution.py` tests that call `detect_snapshot_collisions`

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest tests/test_config.py tests/test_input_resolution.py tests/test_run_orchestration.py tests/test_e2e_smoke.py -v`
Expected: All tests pass

**Commit:** `test: rename sdd to snapshot in all test fixtures and assertions`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Update pyaggregate.toml and documentation

**Verifies:** None (documentation and example config)

**Files:**
- Modify: `pyaggregate.toml` (`[agg.sdd]` → `[agg.snapshot]`)
- Modify: `docs/operations.md` (4 occurrences)
- Modify: `docs/migration.md` (3 occurrences)

**Implementation:**

**pyaggregate.toml** (created in Phase 1):
- `[agg.sdd]` → `[agg.snapshot]`

**docs/operations.md:**
- Line 39: `[agg.sdd]` → `[agg.snapshot]`
- Lines 29-31: The config example still shows `[output]\noutput_root = ...`. Replace the entire config example block with the new per-agg `output_path` schema (remove `[output]` section, add `output_path` to each `[agg.*]` block). Also fix the snapshot config to use `source_field = "has_scdm"` and `subdirectory = "scdm_snapshot"` instead of the pre-existing incorrect `source_reqtype = "qar"`.
- Line 106: `└── sdd/` → `└── snapshot/`
- Line 179: `outputs/sdd/latest` → `outputs/snapshot/latest`
- Line 263: `(qa, qm, sdd)` → `(qa, qm, snapshot)`

**docs/migration.md:**
- Line 41: `[agg.sdd]` → `[agg.snapshot]`
- Lines 30-33: The config example still shows `[output]\noutput_root = ...`. Replace the entire config example block with the new per-agg `output_path` schema (remove `[output]` section, add `output_path` to each `[agg.*]` block).
- Line 59: `sdd/latest /tmp/baseline-sdd-latest` → `snapshot/latest /tmp/baseline-snapshot-latest`
- Line 497: `outputs/sdd/latest/` → `outputs/snapshot/latest/`

Do NOT modify any files in `docs/design-plans/` or `docs/test-plans/` — those are historical records.

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -c "from pyaggregate.config import load_config; from pathlib import Path; c = load_config(Path('pyaggregate.toml')); print(list(c.agg_types.keys()))"`
Expected: `['qa', 'qm', 'snapshot']`

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn '"sdd"\|agg\.sdd\|/sdd/' src/ tests/ pyaggregate.toml docs/operations.md docs/migration.md`
Expected: No matches (all `sdd` as identifier should be gone from these locations)

**Commit:** `docs: rename sdd to snapshot in config and documentation`

<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_4 -->
### Task 4: Full suite verification

**Verifies:** None (cross-cutting verification)

**Files:** None (verification only)

**Implementation:**

Run the full pytest suite to ensure no `sdd` references remain as identifiers and everything passes.

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest -v`
Expected: All tests pass

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn "sdd" src/ tests/ --include="*.py" | grep -v "has_scdm\|scdm_snapshot\|glob_scdm\|SCDM"`
Expected: No matches — only `has_scdm`, `scdm_snapshot`, `glob_scdm_tables`, and `SCDM` proper noun refs remain

**Commit:** No commit — verification only. If issues found, fix and commit: `fix: remove remaining sdd identifier references`

<!-- END_TASK_4 -->
