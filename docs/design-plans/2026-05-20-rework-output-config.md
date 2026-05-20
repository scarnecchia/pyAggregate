# Rework Output Config Design

## Summary

pyaggregate currently routes all agg-type outputs through a single global `output_root` directory, composing paths as `{output_root}/{agg_type}/{run_id}/{output_type}/<table>.parquet`. This design couples all agg types to a shared filesystem root and bakes the agg-type identifier into the path, limiting flexibility when different agg types need to land in different locations (or when the containing directory already implies the type).

This rework decentralizes output configuration by moving `output_path` from a global `[output]` section into each individual `[agg.X]` TOML block. Each agg type becomes fully self-contained: it owns its root, its `latest` symlink, and its path layout. The writer drops the `agg_type` segment from the composed path entirely, simplifying it to `{output_path}/{run_id}/{output_type}/<table>.parquet`. Concurrently, the agg-type identifier `sdd` is hard-renamed to `snapshot` end-to-end — config keys, CLI arguments, function names, tests, and docs — with no migration shim since there are no production users.

## Definition of Done

1. Running pyaggregate with a config that defines `output_path` per agg_type writes outputs to those exact locations using the layout `{output_path}/{run_id}/{output_type}/<table>.parquet`.
2. The agg_type formerly known as `sdd` is renamed to `snapshot` end-to-end (config keys, CLI `--type` value, code references, logs, and run summaries).
3. The `latest` symlink continues to work, now living at `{output_path}/latest -> {run_id}` (per agg_type, since each has its own root).
4. The global `[output]` config section, `OutputConfig`, `output_root` field, and `--output-root` CLI flag are removed entirely; configs that still use them are rejected with a clear error.
5. Existing test suite passes with fixtures updated to the new config shape; new tests cover per-agg-type path resolution and rejection of the old `[output]` schema.

## Acceptance Criteria

### rework-output-config.AC1: Per-agg output_path is honoured

- **rework-output-config.AC1.1 Success:** Given a config where `[agg.snapshot]` declares `output_path = "/tmp/foo/snapshot"`, running pyaggregate writes table parquet files to `/tmp/foo/snapshot/{run_id}/{stacked,masked,rollup}/<table>.parquet`.
- **rework-output-config.AC1.2 Success:** A single config invocation that runs multiple agg types (e.g., `--type snapshot --type qa --type qm`) writes each agg's outputs to its own configured `output_path` — the three trees do not share a common parent in the path layout.
- **rework-output-config.AC1.3 Success:** `output_path` values containing `~` are expanded to the user's home directory at config-load time.
- **rework-output-config.AC1.4 Failure:** A config missing `output_path` for any declared `[agg.X]` block is rejected at load time with a `ValueError` whose message names the agg block (e.g., `[agg.snapshot]`) and the missing field.
- **rework-output-config.AC1.5 Edge:** A relative `output_path` is accepted as-is (not absolutized) and resolved relative to the current working directory at write time, preserving current `output_root` behaviour.

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

- **rework-output-config.AC4.1 Failure:** A config containing an `[output]` section is rejected at load time with a `ValueError` whose message states the section was removed and points to the new per-agg `output_path` field with a concrete example.
- **rework-output-config.AC4.2 Failure:** A config containing `output_root` as a key inside any `[output]`-like section is rejected with the same migration message (not silently accepted or ignored).
- **rework-output-config.AC4.3 Failure:** Invoking the CLI with `--output-root /some/path` exits non-zero with a typer error stating `--output-root` is not a recognized option.

### rework-output-config.AC5: sdd to snapshot rename

- **rework-output-config.AC5.1 Success:** CLI invocation with `--type snapshot` selects the snapshot agg type and runs the same aggregation logic that `--type sdd` previously selected.
- **rework-output-config.AC5.2 Failure:** CLI invocation with `--type sdd` against a config that declares `[agg.snapshot]` (and no `[agg.sdd]`) exits non-zero with an "unknown agg type" error listing the configured types.
- **rework-output-config.AC5.3 Success:** `detect_snapshot_collisions()` (renamed from `detect_sdd_collisions`) is importable from `src/pyaggregate/core/input_resolution.py` and produces the same collision-detection behaviour for snapshot-type input resolution.

### rework-output-config.AC6: Cross-cutting

- **rework-output-config.AC6.1 Success:** The full `pytest` suite passes with the refactor in place; no test still references `OutputConfig`, `output_root`, `--output-root`, or `sdd` as an agg-type identifier.
- **rework-output-config.AC6.2 Success:** `pyaggregate.toml` (the root example config) reflects the new schema and is loadable by `load_config()` without modification.

## Glossary

- **agg type / agg_type**: A named aggregation pipeline variant (e.g., `snapshot`, `qa`, `qm`). Each is configured under its own `[agg.X]` TOML block and produces a distinct set of Parquet output tables.
- **`output_path`**: A per-agg-type filesystem path (new field) that serves as the root directory for that agg's outputs, replacing the former global `output_root`.
- **`output_root`**: The former global config field (now removed) that provided a single shared filesystem root for all agg types. Configs still using it are rejected with a migration error.
- **`OutputConfig`**: The Python dataclass (now deleted) that held the global `output_root` value. Referenced here to clarify what is being removed.
- **`run_id`**: A unique identifier for a single pipeline invocation, used as a path segment to keep each run's outputs isolated under the agg's `output_path`.
- **`output_type`**: The sub-category of output within a run — one of `stacked`, `masked`, or `rollup` — corresponding to different stages of the aggregation.
- **`latest` symlink**: A filesystem symbolic link at `{output_path}/latest` that points to the most recent `run_id` directory, allowing consumers to always read the latest outputs without knowing the exact run identifier.
- **Temp-then-rename atomicity**: A write pattern where a file or symlink is first written to a `.tmp` location, then moved into place with `os.rename`, ensuring readers never observe a partial or missing state during the update.
- **Functional Core / Imperative Shell (FCIS)**: An architectural pattern that separates pure business logic (no side effects) from code that performs I/O. In this codebase, `writer.py` is the Imperative Shell — it owns all filesystem writes.
- **`@dataclass(frozen=True)`**: A Python dataclass that is immutable after construction. Used for config classes to prevent accidental mutation post-load.
- **TOML**: The configuration file format used by pyaggregate (`pyaggregate.toml`). TOML sections map directly to Python dataclass instances via the config loader.
- **`expanduser()`**: A Python `pathlib` method that expands a leading `~` in a path to the current user's home directory. Applied at config load time.
- **`sdd` (SCDM Snapshot)**: The former agg-type identifier for the snapshot aggregation pipeline, renamed to `snapshot` in this rework. Referenced throughout the document to describe what is being replaced.
- **Typer**: The Python CLI framework used to define pyaggregate's command-line interface, including argument parsing and `--flag` validation.

## Architecture

The current output configuration centralizes write destinations under a single global `output_root`. The writer composes paths as `{output_root}/{agg_type}/{run_id}/{output_type}/<table>.parquet` and creates a `latest` symlink at `{output_root}/{agg_type}/latest`. This shape forces all agg types to live under one tree.

The new architecture decentralizes output configuration: each `[agg.X]` block in the TOML config carries its own required `output_path` field. The writer composes paths as `{output_path}/{run_id}/{output_type}/<table>.parquet` and creates a `latest` symlink at `{output_path}/latest`. The `agg_type` segment is no longer injected into the path — it remains a label in logs and `run_summary.json` for traceability, but the user controls its location (or omits it) via the configured `output_path`.

Concurrently, the agg_type identifier `sdd` (SCDM Snapshot) is renamed to `snapshot` end-to-end as a hard rename. There are no production users; no migration shim is required.

**Component changes:**

- `src/pyaggregate/config.py` — `OutputConfig` and `AppConfig.output` removed; `AggTypeConfig.output_path: Path` added as required field; loader rejects obsolete `[output]` section with explicit migration message.
- `src/pyaggregate/io/writer.py` — `write_run` and `check_run_exists` take `output_path: Path` instead of `(output_root, agg_type)`; path composition simplified; latest symlink relocated.
- `src/pyaggregate/cli.py` — `--output-root` option removed; per-agg orchestration reads `cfg.agg_types[t].output_path` and threads it through to the writer.
- `src/pyaggregate/core/input_resolution.py` — `detect_sdd_collisions()` renamed to `detect_snapshot_collisions()`; docstring updates.
- `src/pyaggregate/io/input_resolver.py` — docstring updates for snapshot agg type.

**Data flow:**

```text
TOML config -> load_config() -> AppConfig.agg_types[name].output_path
                                                            |
                                       CLI run() loop ------+
                                                            v
                            write_run(output_path=..., agg_type=name, ...)
                                                            |
                                                            v
                            {output_path}/{run_id}/{output_type}/<table>.parquet
                            {output_path}/latest -> {run_id}
```

## Existing Patterns

Investigation confirmed pyaggregate follows a Functional Core / Imperative Shell pattern. The writer is the Imperative Shell ([writer.py:1](src/pyaggregate/io/writer.py#L1) marks `# pattern: Imperative Shell`); config is dataclass-based and loaded once at startup.

This design follows existing patterns:

- **`@dataclass(frozen=True)` config classes** — `AggTypeConfig` already uses this pattern at [config.py:20](src/pyaggregate/config.py#L20); the new `output_path` field follows it.
- **Explicit validation in `load_config()`** — current loader raises `ValueError` on missing `[output]` ([config.py:105-113](src/pyaggregate/config.py#L105-L113)); the new rejection of `[output]` and validation of per-agg `output_path` mirrors this pattern.
- **Temp-then-rename atomicity in the writer** — [writer.py:76-79](src/pyaggregate/io/writer.py#L76-L79) writes `.tmp` then `os.rename`. The latest symlink already uses the same pattern at [writer.py:125-134](src/pyaggregate/io/writer.py#L125-L134). New path layout preserves both behaviours.
- **Path values stored as `pathlib.Path`** — `expanduser()` applied at load time but not `resolve()`; matches handling of `output_root` in the current loader.
- **Test fixture style** — `tests/test_config.py`, `tests/test_writer.py`, `tests/test_run_orchestration.py` use TOML string fixtures and dataclass builders; new tests follow this style.

No new patterns are introduced. The internet-researcher's Pydantic-based recommendations (`extra="forbid"`, field validators) were considered but not adopted — sticking with the existing dataclass approach maintains consistency.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Config schema rework

**Goal:** `AggTypeConfig` gains `output_path: Path` as a required field; `OutputConfig` and the `[output]` section are deleted; loader rejects the old schema with a clear migration message.

**Components:**

- [src/pyaggregate/config.py](src/pyaggregate/config.py) — remove `OutputConfig` class (currently at lines 49–52), remove `output: OutputConfig` field from `AppConfig` (line 61), remove `[output]` parsing block (lines 105–113); add `output_path: Path` to `AggTypeConfig` (line 20–30); add per-agg `output_path` parsing in the `[agg.*]` loop (lines 119–156); apply `expanduser()` on load; raise `ValueError` with explicit migration text if `[output]` section is present in TOML.
- [tests/test_config.py](tests/test_config.py) — fixture rewrites for the 7 config blocks that use `output_root = "/data/outputs"`; new test for `[output]` rejection; new test for missing-per-agg `output_path` rejection; new test for `~` expansion.
- [pyaggregate.toml](pyaggregate.toml) — root example config updated to new shape.

**Dependencies:** None (first phase).

**Done when:** `pytest tests/test_config.py` passes; obsolete `[output]` schema is rejected with a migration message naming the new field; ACs `rework-output-config.AC1.*` are verified by tests.

**ACs covered:** rework-output-config.AC1.1, AC1.2, AC1.3, AC1.4, AC1.5, AC4.1, AC4.2.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Writer and CLI plumbing

**Goal:** `write_run` and `check_run_exists` take per-agg `output_path` instead of `(output_root, agg_type)`. The CLI removes `--output-root` and threads per-agg paths to the writer. The `latest` symlink moves to `{output_path}/latest`.

**Components:**

- [src/pyaggregate/io/writer.py](src/pyaggregate/io/writer.py) — `write_run(output_path: Path, agg_type: str, run_id: str, ...)` (was `output_root + agg_type`); path composition uses `output_path / run_id / output_type` (was `output_root / agg_type / run_id / output_type`); `latest` symlink at `output_path / "latest"` (was `output_root / agg_type / "latest"`); `check_run_exists(output_path: Path, run_id: str)` signature simplified; docstrings updated.
- [src/pyaggregate/cli.py](src/pyaggregate/cli.py) — remove `output_root: Path | None` parameter (lines 129–132); remove `output_root_path` resolution (line 158); in the per-agg-type orchestration loop, read `cfg.agg_types[t].output_path` and pass to `write_run` (line 181, 184, 237, 248); update CLI help text where it mentions `output_root`.
- [tests/test_writer.py](tests/test_writer.py) — all 30+ assertions and fixtures rewritten to new path shape; latest symlink tests updated (lines 178–223).
- [tests/test_run_orchestration.py](tests/test_run_orchestration.py) — config builder updates (lines 27, 66); 9 path assertions updated; delete `--output-root` CLI flag tests at lines 544–861 (replace with "each agg writes to its own configured `output_path`" coverage); latest symlink assertions move from `cfg.output.output_root / agg_type / "latest"` to `cfg.agg_types[t].output_path / "latest"`.
- [tests/test_scanner.py:69](tests/test_scanner.py#L69), [tests/test_scanner_concurrency.py:96](tests/test_scanner_concurrency.py#L96) — fixture updates.

**Dependencies:** Phase 1 (config schema must allow per-agg `output_path`).

**Done when:** `pytest tests/test_writer.py tests/test_run_orchestration.py tests/test_scanner.py tests/test_scanner_concurrency.py` passes; `--output-root` flag is gone; latest symlinks land at `{output_path}/latest` per agg.

**ACs covered:** rework-output-config.AC2.1, AC2.2, AC2.3, AC2.4, AC3.1, AC3.2, AC3.3, AC4.3.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: sdd to snapshot rename

**Goal:** The agg_type identifier `sdd` is renamed to `snapshot` everywhere — config keys, CLI argument values, function names, docstrings, fixtures, examples, and documentation. "SCDM" the proper noun stays.

**Components:**

- [src/pyaggregate/core/input_resolution.py](src/pyaggregate/core/input_resolution.py) — `detect_sdd_collisions()` renamed to `detect_snapshot_collisions()` (line 125); docstring on line 42 updated.
- [src/pyaggregate/io/input_resolver.py:27](src/pyaggregate/io/input_resolver.py#L27) — docstring update.
- [src/pyaggregate/io/writer.py](src/pyaggregate/io/writer.py) — docstrings at lines 34, 190, 216 updated to list `qa, qm, snapshot`.
- [src/pyaggregate/cli.py:56, 141](src/pyaggregate/cli.py#L56) — CLI help text references updated.
- [pyaggregate.toml:22-25](pyaggregate.toml#L22) — `[agg.sdd]` block renamed to `[agg.snapshot]`.
- [tests/test_input_resolution.py](tests/test_input_resolution.py) — import on line 13; test function names and fixture names at lines 92, 98, 318, 329, 344, 357, 363, 407, 427.
- [tests/test_run_orchestration.py](tests/test_run_orchestration.py) — fixtures and assertions at lines 70, 95, 176, 186, 191, 199, 205, 215, 227–229.
- [tests/test_e2e_smoke.py](tests/test_e2e_smoke.py) — fixtures and loop assertions at lines 57, 120, 204, 267, 313, 372, 414, 442.
- [docs/migration.md](docs/migration.md), [docs/operations.md](docs/operations.md) — references updated to `snapshot` (4+5 occurrences).

**Dependencies:** Phases 1 and 2 (rename touches files already restructured).

**Done when:** `pytest` passes the full suite with `snapshot` everywhere; `grep -r "sdd" src/ tests/` returns no agg-type identifier matches (only historical design-plan refs remain, which are intentionally preserved); `--type snapshot` works; `--type sdd` fails with the natural "unknown agg type" error.

**ACs covered:** rework-output-config.AC5.1, AC5.2, AC5.3.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: E2E smoke and integration verification

**Goal:** End-to-end smoke test passes against the new schema and identifier; manual verification confirms a real config writes outputs to the configured locations.

**Components:**

- [tests/test_e2e_smoke.py](tests/test_e2e_smoke.py) — TOML fixtures provide per-agg `output_path` for all three agg types; assertions verify `{output_path}/{run_id}/{output_type}/<table>.parquet` exists for each agg; `latest` symlink verified at `{output_path}/latest`.
- Manual smoke: invoke pyaggregate with a config matching the target user paths (e.g., `/tmp/.../snapshot/sdd/parquet`, `/tmp/.../qa/sdd/parquet`, `/tmp/.../qm/sdd/parquet`); confirm output layout and symlinks; confirm a config with `[output]` is rejected with the migration message; confirm `--output-root` is no longer accepted by typer.

**Dependencies:** Phases 1–3 complete.

**Done when:** `pytest tests/test_e2e_smoke.py` passes; manual smoke verifies the three target ACs (AC1.1, AC2.1, AC3.1) against real filesystem outputs; full test suite green.

**ACs covered:** rework-output-config.AC1.1, AC2.1, AC3.1 (integration-level), AC6.1.
<!-- END_PHASE_4 -->

## Additional Considerations

**Error message quality:** The `[output]` rejection message must name the new field and point users to the per-agg shape. Suggested wording: `"The [output] section has been removed. Each [agg.X] block must now define output_path. Example: [agg.snapshot]\n  output_path = \"/path/to/output\""`. Missing-`output_path` errors must include the agg-type name (e.g., `"[agg.snapshot] missing required field 'output_path'"`).

**Path resolution timing:** `expanduser()` is applied at config load time; `resolve()` is not. Parent-directory existence is not checked at load time — the writer's `mkdir(parents=True, exist_ok=True)` handles directory creation lazily. This matches current behaviour for `output_root`.

**Cross-mount atomic renames:** `os.rename` is not atomic across filesystem boundaries. With per-agg `output_path` values, users could in theory configure paths on different mounts. The writer's temp-then-rename pattern stays within a single `output_path` tree, so atomicity is preserved per agg. No special handling required.

**Historical design-plan files:** `docs/design-plans/2026-05-14-pyaggregate-unify-qa-qm-sdd.md` and its sibling test plan reference `sdd` as part of the historical record. They are intentionally NOT updated.
