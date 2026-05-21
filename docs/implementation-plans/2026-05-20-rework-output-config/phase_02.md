# Rework Output Config — Phase 2: Writer and CLI Plumbing

**Goal:** `write_run` and `check_run_exists` take per-agg `output_path` instead of `(output_root, agg_type)`. The CLI removes `--output-root` and threads per-agg paths to the writer. The `latest` symlink moves to `{output_path}/latest`.

**Architecture:** Change writer function signatures to accept `output_path: Path` directly. Remove the `agg_type` segment from path composition (`output_path / run_id` instead of `output_root / agg_type / run_id`). Remove CLI `--output-root` option. Update all test fixtures and path assertions.

**Tech Stack:** Python 3.12+, pathlib, typer, polars, pytest

**Scope:** 4 phases from original design (phase 2 of 4)

**Codebase verified:** 2026-05-20

---

## Acceptance Criteria Coverage

This phase implements and tests:

### rework-output-config.AC2: Writer signature and path composition

- **rework-output-config.AC2.1 Success:** `write_run(output_path, agg_type, run_id, ...)` writes `dpid_map.csv` and `run_summary.json` at `{output_path}/{run_id}/`.
- **rework-output-config.AC2.2 Success:** `run_summary.json` continues to include `agg_type` (the label) and `run_id` fields even though `agg_type` no longer appears in the path.
- **rework-output-config.AC2.3 Success:** `check_run_exists(output_path, run_id)` returns `True` iff `{output_path}/{run_id}/` exists.
- **rework-output-config.AC2.4 Failure:** Per-table write failures still land in `tables_skipped` and set exit code 2 — the path refactor does not change failure semantics.

### rework-output-config.AC3: latest symlink

- **rework-output-config.AC3.1 Success:** When `update_latest=True`, the writer creates a symlink at `{output_path}/latest` pointing to the relative path `{run_id}`.
- **rework-output-config.AC3.2 Success:** The latest symlink is created atomically via temp-then-rename; an existing `latest` symlink is replaced without an intermediate window where it is missing or stale.
- **rework-output-config.AC3.3 Success:** Each agg type's latest symlink is independent — running `--type qa` updates only `{qa.output_path}/latest`, not `{snapshot.output_path}/latest`.

### rework-output-config.AC4: Legacy schema rejection

- **rework-output-config.AC4.3 Failure:** Invoking the CLI with `--output-root /some/path` exits non-zero with a typer error stating `--output-root` is not a recognized option.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Refactor writer.py signatures and path composition

**Verifies:** rework-output-config.AC2.1, rework-output-config.AC2.2, rework-output-config.AC2.3, rework-output-config.AC3.1, rework-output-config.AC3.2

**Files:**
- Modify: `src/pyaggregate/io/writer.py:16-24` (write_run signature)
- Modify: `src/pyaggregate/io/writer.py:33-34` (docstring: output_root → output_path)
- Modify: `src/pyaggregate/io/writer.py:44` (path composition: remove agg_type segment)
- Modify: `src/pyaggregate/io/writer.py:125-134` (latest symlink: output_path instead of output_root / agg_type)
- Modify: `src/pyaggregate/io/writer.py:190` (docstring: agg_type list)
- Modify: `src/pyaggregate/io/writer.py:211-223` (check_run_exists: remove agg_type param, simplify path)
- Modify: `src/pyaggregate/io/writer.py:215-216` (docstring: output_root → output_path)

**Implementation:**

1. **`write_run` signature** (line 16): Change `output_root: Path` to `output_path: Path`. Keep `agg_type: str` — it's still needed for `run_summary.json` and logging, just not for path composition.

2. **`write_run` docstring** (lines 25-39): Update:
   - Line 27: `output_root/<agg_type>/<run_id>/<output_type>/` → `output_path/<run_id>/<output_type>/`
   - Line 33: `output_root: Root directory for outputs` → `output_path: Per-agg output directory`

3. **Path composition** (line 44): Change `run_dir = output_root / agg_type / run_id` to `run_dir = output_path / run_id`.

4. **Latest symlink** (lines 125-128): Change:
   ```python
   latest_dir = output_root / agg_type
   latest_path = latest_dir / "latest"
   latest_tmp = latest_dir / f"latest.{tempfile.gettempprefix()}{os.getpid()}"
   ```
   to:
   ```python
   latest_path = output_path / "latest"
   latest_tmp = output_path / f"latest.{tempfile.gettempprefix()}{os.getpid()}"
   ```
   The symlink now lives at `{output_path}/latest` instead of `{output_root}/{agg_type}/latest`.

5. **`check_run_exists`** (lines 211-223): Remove the `agg_type` parameter. Change signature to `check_run_exists(output_path: Path, run_id: str) -> bool`. Change path composition from `output_root / agg_type / run_id` to `output_path / run_id`. Update docstring accordingly.

**Verification:**
Run: `python -c "from pyaggregate.io.writer import write_run, check_run_exists; import inspect; sig = inspect.signature(write_run); print(list(sig.parameters.keys())); sig2 = inspect.signature(check_run_exists); print(list(sig2.parameters.keys()))"`
Expected: `['output_path', 'agg_type', 'run_id', 'table_outputs', 'dpid_map_frame', 'update_latest', 'tables_skipped']` and `['output_path', 'run_id']`

**Commit:** `refactor: writer uses output_path instead of output_root/agg_type`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update test_writer.py for new path layout

**Verifies:** rework-output-config.AC2.1, rework-output-config.AC2.2, rework-output-config.AC2.3, rework-output-config.AC3.1, rework-output-config.AC3.2

**Files:**
- Modify: `tests/test_writer.py` (all test functions and assertions)

**Implementation:**

Every test in this file calls `write_run(output_root=..., agg_type="qa", ...)` and asserts paths like `output_root / "qa" / run_id / ...`. The changes are mechanical:

1. **All `write_run()` calls**: Change keyword `output_root=output_root` to `output_path=output_path`. The local variable can be renamed from `output_root` to `output_path` for clarity, or kept — the key change is the keyword argument name.

2. **Path variable**: Change `output_root = tmp_path / "outputs"` to `output_path = tmp_path / "outputs"` (or keep `output_root` as local var name — the important thing is the kwarg). For clarity and to avoid confusion, rename to `output_path`.

3. **All path assertions**: Remove the `"qa"` segment from paths. For example:
   - `output_root / "qa" / "2026-05-14" / "stacked"` → `output_path / "2026-05-14" / "stacked"`
   - `output_root / "qa" / "2026-05-14" / "stacked" / "ae.parquet"` → `output_path / "2026-05-14" / "stacked" / "ae.parquet"`
   - `output_root / "qa" / "2026-05-14" / "dpid_map.csv"` → `output_path / "2026-05-14" / "dpid_map.csv"`
   - `output_root / "qa" / "latest"` → `output_path / "latest"`

4. **`check_run_exists` calls**: Change from `check_run_exists(output_root, "qa", "2026-05-14")` to `check_run_exists(output_path, "2026-05-14")` (remove `agg_type` argument).

5. **Orphaned tmp cleanup test** (line 333): Change `run_dir = output_root / "qa" / "2026-05-14"` to `run_dir = output_path / "2026-05-14"`.

This is a mechanical find-and-replace across 17 test functions. No test logic changes — only path shapes and keyword argument names.

**Testing:**
Tests verify the ACs after path changes:
- rework-output-config.AC2.1: `test_write_run_creates_directory_structure`, `test_write_run_dpid_map_filtered`, `test_write_run_summary_json` — dpid_map.csv and run_summary.json at `{output_path}/{run_id}/`
- rework-output-config.AC2.2: `test_write_run_summary_json` — summary still includes `agg_type` and `run_id`
- rework-output-config.AC2.3: `test_check_run_exists_returns_true`, `test_check_run_exists_returns_false` — new 2-arg signature
- rework-output-config.AC3.1: `test_write_run_latest_symlink_created` — symlink at `{output_path}/latest`
- rework-output-config.AC3.2: `test_write_run_atomic_symlink_update` — atomic swap still works

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest tests/test_writer.py -v`
Expected: All 17 tests pass

**Commit:** `test: update test_writer.py path assertions for per-agg output_path`

<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->

<!-- START_TASK_3 -->
### Task 3: Update CLI to remove --output-root and thread per-agg output_path

**Verifies:** rework-output-config.AC4.3

**Files:**
- Modify: `src/pyaggregate/cli.py:129-132` (remove `--output-root` option from `run` command signature)
- Modify: `src/pyaggregate/cli.py:158` (remove `output_root_path` resolution)
- Modify: `src/pyaggregate/cli.py:181` (update `check_run_exists` call)
- Modify: `src/pyaggregate/cli.py:184` (update error message path)
- Modify: `src/pyaggregate/cli.py:236-244` (update `write_run` call)
- Modify: `src/pyaggregate/cli.py:248` (update success echo path)

**Implementation:**

1. **Remove `--output-root` parameter** (lines 129-132): Delete the entire `output_root: Path | None = typer.Option(...)` parameter from the `run` function signature.

2. **Remove `output_root_path` resolution** (line 158): Delete `output_root_path = output_root if output_root is not None else cfg.output.output_root`. This line accessed `cfg.output` which no longer exists after Phase 1.

3. **Inside the per-agg loop** (starting line 170), after `agg_config = cfg.agg_types[agg_type]` (line 178), use `agg_config.output_path` directly:

4. **Update `check_run_exists` call** (line 181): Change from `check_run_exists(output_root_path, agg_type, run_id)` to `check_run_exists(agg_config.output_path, run_id)`.

5. **Update error message** (line 184): Change `{output_root_path / agg_type / run_id}` to `{agg_config.output_path / run_id}`.

6. **Update `write_run` call** (lines 236-244): Change `output_root=output_root_path` to `output_path=agg_config.output_path`.

7. **Update success echo** (line 248): Change `{output_root_path / agg_type / run_id}` to `{agg_config.output_path / run_id}`.

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pyaggregate run --help | grep -c "output-root"`
Expected: `0` (flag no longer appears in help)

**Commit:** `refactor: remove --output-root CLI flag, thread per-agg output_path`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Update test_run_orchestration.py for new config and path shapes

**Verifies:** rework-output-config.AC2.4, rework-output-config.AC3.1, rework-output-config.AC3.3, rework-output-config.AC4.3

**Files:**
- Modify: `tests/test_run_orchestration.py:13` (remove `OutputConfig` import)
- Modify: `tests/test_run_orchestration.py:24-102` (update `test_config` fixture)
- Modify: `tests/test_run_orchestration.py:196-868` (update all `TestRunOrchestration` path assertions)
- Modify: `tests/test_run_orchestration.py:544-572` (rewrite `test_run_with_alternate_output_root`)
- Modify: `tests/test_run_orchestration.py:609-675` (update `test_run_with_alternate_catalog_ac4_1` config fixture)
- Modify: `tests/test_run_orchestration.py:709-753` (rewrite `test_run_with_alternate_output_root_ac4_2`)

**Implementation:**

1. **Import** (line 13): Remove `OutputConfig` from the import list.

2. **`test_config` fixture** (lines 24-102):
   - Line 27: Keep `output_root = tmp_path / "outputs"` as a base for constructing per-agg output_path values.
   - Lines 63-72: Remove `output=OutputConfig(output_root=output_root)` from `AppConfig(...)`. Add `output_path` to each `AggTypeConfig`:
     ```python
     config = AppConfig(
         scan=ScanConfig(requests_root=Path("/data/requests")),
         state=StateConfig(catalog_db=catalog_db, log_dir=tmp_path / "logs"),
         agg_types={
             "qa": AggTypeConfig(name="qa", source_reqtype="qar", output_path=output_root / "qa", exclude_from_rollup=("*_stats",)),
             "qm": AggTypeConfig(name="qm", source_reqtype="qmr", output_path=output_root / "qm", exclude_from_rollup=("*_stats",)),
             "sdd": AggTypeConfig(name="sdd", source_field="has_scdm", output_path=output_root / "sdd", subdirectory="scdm_snapshot", exclude_from_rollup=()),
         },
     )
     ```
   - Lines 74-99: Update the TOML config string to remove `[output]` section and add `output_path` to each `[agg.*]` block:
     ```python
     config_file.write_text(
         """
     [scan]
     requests_root = "/data/requests"

     [state]
     catalog_db = "{}"
     log_dir = "{}"

     [agg.qa]
     source_reqtype = "qar"
     output_path = "{}"
     exclude_from_rollup = ["*_stats"]

     [agg.qm]
     source_reqtype = "qmr"
     output_path = "{}"
     exclude_from_rollup = ["*_stats"]

     [agg.sdd]
     source_field = "has_scdm"
     subdirectory = "scdm_snapshot"
     output_path = "{}"
     exclude_from_rollup = []
     """.format(catalog_db, tmp_path / "logs", output_root / "qa", output_root / "qm", output_root / "sdd")
     )
     ```

3. **Path assertions across TestRunOrchestration**: All paths that currently use `config.output.output_root / agg_type / ...` must change to `config.agg_types[agg_type].output_path / ...`. Key changes:
   - `config.output.output_root / "qa" / date.today().isoformat()` → `config.agg_types["qa"].output_path / date.today().isoformat()`
   - `config.output.output_root / "sdd" / date.today().isoformat()` → `config.agg_types["sdd"].output_path / date.today().isoformat()`
   - `config.output.output_root / "qm"` → `config.agg_types["qm"].output_path`
   - `config.output.output_root / "qa" / "latest"` → `config.agg_types["qa"].output_path / "latest"`

4. **`test_run_with_alternate_output_root` (lines 544-572) and `test_run_with_alternate_output_root_ac4_2` (lines 709-753)**: These tests validate `--output-root` which no longer exists. **Delete both test methods** and **replace with a single AC4.3 rejection test**:

   ```python
   def test_run_output_root_flag_rejected_ac4_3(
       self,
       cli_runner: CliRunner,
       test_config: tuple[Path, AppConfig],
   ) -> None:
       """AC4.3: --output-root is no longer a recognized CLI option."""
       config_file, config = test_config

       result = cli_runner.invoke(
           app,
           [
               "run",
               "--type",
               "qa",
               "--output-root",
               "/some/path",
               "--config",
               str(config_file),
           ],
       )

       assert result.exit_code != 0
   ```

   This explicitly verifies AC4.3 rather than relying on the absence of the old tests.

5. **`test_run_with_alternate_catalog_ac4_1`** (lines 609-675): Update the TOML string at lines 661-675 to remove `[output]` section and add `output_path` per agg block.

6. **Symlink assertions** (lines 498-542, 755-808, 810-868): Change `config.output.output_root / "qa" / "latest"` to `config.agg_types["qa"].output_path / "latest"`.

**Testing:**
Tests verify the ACs:
- rework-output-config.AC2.4: `test_run_partial_failure_exit_code_2`, `test_run_full_failure_exit_code_1` — failure semantics unchanged
- rework-output-config.AC3.1: `test_run_updates_latest_symlink_on_success` — symlink at per-agg output_path
- rework-output-config.AC3.3: `test_run_with_type_filter_qa_sdd_only` — each agg writes to its own output_path
- rework-output-config.AC4.3: `test_run_output_root_flag_rejected_ac4_3` — explicit test that `--output-root` is rejected by CLI

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest tests/test_run_orchestration.py -v`
Expected: All tests pass (minus the 2 deleted tests)

**Commit:** `test: update test_run_orchestration for per-agg output_path, remove --output-root tests`

<!-- END_TASK_4 -->

<!-- END_SUBCOMPONENT_B -->

<!-- START_SUBCOMPONENT_C (tasks 5-6) -->

<!-- START_TASK_5 -->
### Task 5: Update scanner test fixtures

**Verifies:** None (fixture updates — no new ACs, just keeping tests passing)

**Files:**
- Modify: `tests/test_scanner.py:61-71` (update `create_config` helper)
- Modify: `tests/test_scanner.py` (imports — remove `OutputConfig` if imported)
- Modify: `tests/test_scanner_concurrency.py:90-98` (update `AppConfig` construction)
- Modify: `tests/test_scanner_concurrency.py` (imports — remove `OutputConfig` if imported)

**Implementation:**

1. **test_scanner.py** (lines 61-71): The `create_config` helper builds `AppConfig` with `output=OutputConfig(output_root=tmp_path / "output")`. Since `AppConfig` no longer has an `output` field, remove that line. The `agg_types={}` is empty so no `output_path` is needed:
   ```python
   def create_config(requests_root: Path, catalog_db: Path, tmp_path: Path) -> AppConfig:
       """Create test AppConfig."""
       return AppConfig(
           scan=ScanConfig(requests_root=requests_root),
           state=StateConfig(
               catalog_db=catalog_db,
               log_dir=tmp_path / "logs",
           ),
           agg_types={},
       )
   ```
   Also remove `OutputConfig` from the import statement in this file.

2. **test_scanner_concurrency.py** (lines 90-98): Same change — remove `output=OutputConfig(...)` from `AppConfig(...)` construction. Remove `OutputConfig` from imports.

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest tests/test_scanner.py tests/test_scanner_concurrency.py -v`
Expected: All tests pass

**Commit:** `test: remove OutputConfig from scanner test fixtures`

<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Run full test suite

**Verifies:** None (integration verification)

**Files:** None (verification only)

**Implementation:**

Run the full pytest suite to catch any remaining references to `OutputConfig`, `output_root`, or `cfg.output` that were missed.

**Verification:**
Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && python -m pytest -v`
Expected: All tests pass

Run: `cd /home/scarndp/dev/Sentinel/pyAggregate && grep -rn "OutputConfig\|cfg\.output\.\|output_root" src/ tests/ --include="*.py" | grep -v "test_config.py.*output_root.*migration\|design-plan"`
Expected: No matches (all references should be gone except test_config.py's legacy rejection test)

**Commit:** No commit — verification only. If issues are found, fix them and commit: `fix: remove remaining output_root references`

<!-- END_TASK_6 -->

<!-- END_SUBCOMPONENT_C -->
