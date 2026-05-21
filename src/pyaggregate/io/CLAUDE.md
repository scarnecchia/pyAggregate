# I/O Layer

Last verified: 2026-05-20

## Purpose
Isolates all filesystem and database side effects from the pure domain logic
in `core/`. Every function here is an Imperative Shell adapter.

## Contracts

### writer.py
- **`write_run(output_path, agg_type, run_id, ...)`**: Writes parquet to `output_path/<run_id>/<output_type>/`. `output_path` comes from `AggTypeConfig.output_path` (per-agg, not a global root). Uses atomic temp-then-rename for all files including the `latest` symlink.
- **`check_run_exists(output_path, run_id)`**: Two-arg signature. No `agg_type` parameter -- the agg-type nesting is handled by the config-level `output_path`.
- **`build_run_summary(agg_type, run_id, ...)`**: `agg_type` is the first positional arg. Returns dict for JSON serialization.
- **Guarantees**: No partial writes visible (atomic rename). `dpid_map.csv` filtered to only surrogates present in masked outputs. `run_summary.json` always written.

### scanner.py
- **`run_scan(cfg, store)`**: Walks requests tree, upserts catalog rows. Returns ScanResult with counts.
- **`run_scan_dry(cfg, store)`**: Returns list of intended changes without modifying catalog.
- **Guarantees**: Concurrent scans blocked via SQLite advisory lock.

### input_resolver.py
- **`resolve_inputs(catalog, agg_config)`**: Orchestrates filter -> glob -> group. For snapshot agg types, globs from `subdirectory`; for qa/qm, globs root of msoc_path.
- **Expects**: `source_field` requires `subdirectory` to also be set.

### catalog_store.py
- SQLite-backed store for catalog, dpid_map, and scan_log.
- Context manager interface (`with CatalogStore(path) as store:`).

## Dependencies
- **Uses**: `pyaggregate.config` (AggTypeConfig, AppConfig), `pyaggregate.core.input_resolution` (pure filtering)
- **Used by**: `pyaggregate.cli`
- **Boundary**: Never import from `cli.py`. Never contain business logic -- delegate to `core/`.

## Key Decisions
- Per-agg output_path (not global output_root): Allows different agg types to write to different mount points. Output directory layout is `output_path/<run_id>/` not `output_root/<agg_type>/<run_id>/`.
- Atomic writes via temp-rename: Prevents consumers from reading partial files.

## Invariants
- All file writes use temp-then-rename (no direct writes to final paths)
- `latest` symlink always points to a relative run_id (not absolute path)
- dpid_map.csv only contains surrogates that appear in masked outputs
