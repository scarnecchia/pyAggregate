# Rework Output Config — Phase 1: Config Schema Rework

**Goal:** `AggTypeConfig` gains `output_path: Path` as a required field; `OutputConfig` and the `[output]` section are deleted; loader rejects the old schema with a clear migration message.

**Architecture:** Remove the global `OutputConfig` dataclass and `[output]` TOML section. Add `output_path: Path` to `AggTypeConfig` with `expanduser()` at load time. Reject legacy `[output]` with actionable migration error. Update `AppConfig` to drop the `output` field.

**Tech Stack:** Python 3.12+, dataclasses, tomllib, pathlib, pytest

**Scope:** 4 phases from original design (phase 1 of 4)

**Codebase verified:** 2026-05-20

---

## Acceptance Criteria Coverage

This phase implements and tests:

### rework-output-config.AC1: Per-agg output_path is honoured

- **rework-output-config.AC1.1 Success:** Given a config where `[agg.snapshot]` declares `output_path = "/tmp/foo/snapshot"`, running pyaggregate writes table parquet files to `/tmp/foo/snapshot/{run_id}/{stacked,masked,rollup}/<table>.parquet`.
- **rework-output-config.AC1.2 Success:** A single config invocation that runs multiple agg types (e.g., `--type snapshot --type qa --type qm`) writes each agg's outputs to its own configured `output_path` — the three trees do not share a common parent in the path layout.
- **rework-output-config.AC1.3 Success:** `output_path` values containing `~` are expanded to the user's home directory at config-load time.
- **rework-output-config.AC1.4 Failure:** A config missing `output_path` for any declared `[agg.X]` block is rejected at load time with a `ValueError` whose message names the agg block (e.g., `[agg.snapshot]`) and the missing field.
- **rework-output-config.AC1.5 Edge:** A relative `output_path` is accepted as-is (not absolutized) and resolved relative to the current working directory at write time, preserving current `output_root` behaviour.

### rework-output-config.AC4: Legacy schema rejection

- **rework-output-config.AC4.1 Failure:** A config containing an `[output]` section is rejected at load time with a `ValueError` whose message states the section was removed and points to the new per-agg `output_path` field with a concrete example.
- **rework-output-config.AC4.2 Failure:** A config containing `output_root` as a key inside any `[output]`-like section is rejected with the same migration message (not silently accepted or ignored).

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Remove OutputConfig and update AggTypeConfig in config.py

**Verifies:** rework-output-config.AC1.3, rework-output-config.AC1.4, rework-output-config.AC1.5, rework-output-config.AC4.1, rework-output-config.AC4.2

**Files:**
- Modify: `src/pyaggregate/config.py:19-30` (add `output_path` to `AggTypeConfig`)
- Modify: `src/pyaggregate/config.py:48-53` (delete `OutputConfig`)
- Modify: `src/pyaggregate/config.py:55-62` (remove `output` field from `AppConfig`)
- Modify: `src/pyaggregate/config.py:105-113` (replace `[output]` parsing with rejection)
- Modify: `src/pyaggregate/config.py:119-156` (add `output_path` parsing in agg loop)
- Modify: `src/pyaggregate/config.py:158-163` (remove `output=output` from AppConfig construction)

**Implementation:**

1. In `AggTypeConfig` (line 19), add `output_path: Path` as the second field (after `name`). It has no default — it is required.

2. Delete the `OutputConfig` class entirely (lines 48-53).

3. In `AppConfig` (lines 55-62), remove the `output: OutputConfig` field. The class becomes:
   ```python
   @dataclass(frozen=True)
   class AppConfig:
       """Top-level application configuration."""

       scan: ScanConfig
       state: StateConfig
       agg_types: dict[str, AggTypeConfig]
   ```

4. Replace the `[output]` parsing block (lines 105-113) with a rejection guard:
   ```python
   if "output" in data:
       raise ValueError(
           "The [output] section has been removed. Each [agg.X] block must now "
           "define output_path. Example:\n"
           '  [agg.snapshot]\n  output_path = "/path/to/output"'
       )
   ```

5. Inside the per-agg loop (after line 123 where `subdirectory` is parsed), add `output_path` extraction:
   ```python
   if "output_path" not in agg_config:
       raise ValueError(
           f"[agg.{agg_name}] missing required field 'output_path'"
       )
   output_path = Path(agg_config["output_path"]).expanduser()
   ```
   Note: `expanduser()` is applied at load time. No `resolve()` — relative paths stay relative (AC1.5).

6. Add `output_path=output_path` to the `AggTypeConfig(...)` constructor call (line 148).

7. Remove `output=output` from the `AppConfig(...)` constructor (line 161). Remove the now-unused `output` local variable.

**Verification:**
Run: `python -c "from pyaggregate.config import AppConfig, AggTypeConfig, load_config; print('imports OK')"`
Expected: `imports OK` (no `OutputConfig` import errors yet — tests will catch that)

**Commit:** `refactor: move output_path into AggTypeConfig, remove OutputConfig`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update test_config.py fixtures and add new validation tests

**Verifies:** rework-output-config.AC1.3, rework-output-config.AC1.4, rework-output-config.AC1.5, rework-output-config.AC4.1, rework-output-config.AC4.2

**Files:**
- Modify: `tests/test_config.py:9-16` (remove `OutputConfig` import)
- Modify: `tests/test_config.py:22-85` (update `test_load_valid_config` fixture and assertions)
- Modify: `tests/test_config.py:86-99` (update `test_missing_scan_section` fixture)
- Modify: `tests/test_config.py:101-116` (update `test_missing_requests_root` fixture)
- Modify: `tests/test_config.py:118-148` (update `test_table_override_parsing` fixture)
- Modify: `tests/test_config.py:150-172` (update `test_exclude_from_rollup_defaults_to_empty` fixture)
- Modify: `tests/test_config.py:174-200` (update `test_dataclass_frozen` fixture)
- Modify: `tests/test_config.py` (add new test methods to `TestLoadConfig`)

**Implementation:**

1. Remove `OutputConfig` from the import block (line 11).

2. In every TOML fixture string that contains `[output]\noutput_root = "/data/outputs"`, remove those two lines entirely and add `output_path = "/data/outputs"` inside each `[agg.X]` block. There are 6 fixtures to update: `test_load_valid_config`, `test_missing_scan_section`, `test_missing_requests_root`, `test_table_override_parsing`, `test_exclude_from_rollup_defaults_to_empty`, `test_dataclass_frozen`.

   Example for `test_load_valid_config` — the TOML becomes:
   ```toml
   [scan]
   requests_root = "/data/requests"

   [state]
   catalog_db = "/data/state/catalog.db"
   log_dir = "/data/state/logs"

   [agg.qa]
   source_reqtype = "qar"
   output_path = "/data/outputs/qa"
   exclude_from_rollup = ["*_stats"]

   [agg.qm]
   source_reqtype = "qmr"
   output_path = "/data/outputs/qm"
   exclude_from_rollup = ["*_stats"]

   [agg.sdd]
   source_field = "has_scdm"
   subdirectory = "scdm_snapshot"
   output_path = "/data/outputs/sdd"
   exclude_from_rollup = []
   ```

   Note: fixtures that don't declare `[agg.*]` blocks (like `test_missing_scan_section`) don't need `output_path` since no agg blocks are parsed.

   Note: Fixtures still use `[agg.sdd]` — this is correct for Phase 1. The rename to `[agg.snapshot]` happens in Phase 3.

3. In `test_load_valid_config` assertions:
   - Remove `assert isinstance(config.output, OutputConfig)` (line 56)
   - Remove `assert config.output.output_root == Path("/data/outputs")` (line 67)
   - Add assertion: `assert config.agg_types["qa"].output_path == Path("/data/outputs/qa")`
   - Add assertion: `assert config.agg_types["sdd"].output_path == Path("/data/outputs/sdd")`

4. In `test_dataclass_frozen`, remove the `OutputConfig` mutation block or replace with an `AggTypeConfig.output_path` mutation test.

5. Add these new test methods to `TestLoadConfig`:

   **`test_legacy_output_section_rejected`** — verifies AC4.1 and AC4.2:
   Write a TOML with `[output]\noutput_root = "/data/outputs"` alongside valid `[scan]` and `[state]`. Assert `pytest.raises(ValueError, match="\\[output\\] section has been removed")`.

   **`test_missing_output_path_rejected`** — verifies AC1.4:
   Write a TOML with `[agg.qa]` that has `source_reqtype` but no `output_path`. Assert `pytest.raises(ValueError, match="\\[agg\\.qa\\].*output_path")`.

   **`test_output_path_tilde_expansion`** — verifies AC1.3:
   Write a TOML with `[agg.qa]\noutput_path = "~/outputs/qa"`. Load config. Assert `config.agg_types["qa"].output_path == Path.home() / "outputs" / "qa"`.

   **`test_output_path_relative_preserved`** — verifies AC1.5:
   Write a TOML with `[agg.qa]\noutput_path = "relative/path"`. Load config. Assert `config.agg_types["qa"].output_path == Path("relative/path")` (not resolved to absolute).

**Testing:**
Tests must verify each AC listed above:
- rework-output-config.AC1.3: `test_output_path_tilde_expansion` — `~` expanded to home dir at load time
- rework-output-config.AC1.4: `test_missing_output_path_rejected` — missing output_path raises ValueError naming the agg block
- rework-output-config.AC1.5: `test_output_path_relative_preserved` — relative path stays relative
- rework-output-config.AC4.1: `test_legacy_output_section_rejected` — `[output]` section rejected with migration message
- rework-output-config.AC4.2: `test_legacy_output_section_rejected` — `output_root` key triggers same rejection

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest tests/test_config.py -v`
Expected: All tests pass

**Commit:** `test: update config fixtures for per-agg output_path, add validation tests`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Create pyaggregate.toml example config

**Verifies:** None (infrastructure — example config file)

**Files:**
- Create: `pyaggregate.toml`

**Implementation:**

Create the root example config reflecting the new schema. This file does not currently exist in the repo (confirmed by investigation). It should be a working example that `load_config()` can parse:

```toml
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "/data/outputs/qa"
exclude_from_rollup = ["*_stats"]

[agg.qm]
source_reqtype = "qmr"
output_path = "/data/outputs/qm"
exclude_from_rollup = ["*_stats"]

[agg.sdd]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "/data/outputs/sdd"
exclude_from_rollup = []
```

Note: This still uses `[agg.sdd]` — the rename to `[agg.snapshot]` happens in Phase 3.

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -c "from pyaggregate.config import load_config; from pathlib import Path; c = load_config(Path('pyaggregate.toml')); print(f'Loaded {len(c.agg_types)} agg types: {list(c.agg_types.keys())}')"`
Expected: `Loaded 3 agg types: ['qa', 'qm', 'sdd']`

**Commit:** `chore: add pyaggregate.toml example config with per-agg output_path`

<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->
