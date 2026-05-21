# pyAggregate

Last verified: 2026-05-21

## Tech Stack
- Language: Python 3.11+
- CLI: Typer
- Data: Polars (parquet output, SAS7BDAT input via polars-readstat), PyArrow (parquet metadata)
- Config: TOML (tomllib)
- Database: SQLite (catalog store)
- Testing: pytest, Hypothesis

## Commands
- `pytest` - Run tests
- `ruff check src/ tests/` - Lint
- `mypy src/` - Type check
- `pyaggregate scan` - Walk requests tree, update catalog
- `pyaggregate run` - Produce aggregated parquet outputs
- `pyaggregate init-db` - Create SQLite catalog

## Project Structure
- `src/pyaggregate/cli.py` - Typer CLI entry point (Imperative Shell)
- `src/pyaggregate/config.py` - TOML config loader and frozen dataclasses
- `src/pyaggregate/core/` - Pure domain logic (pipeline, input resolution, masking)
- `src/pyaggregate/io/` - I/O adapters (writer, scanner, catalog store, SAS reader)
- `docs/` - Operations and migration guides
- `pyaggregate.example.toml` - Reference config

## Architecture
- Functional Core / Imperative Shell pattern (annotated with `# pattern:` comments)
- Frozen dataclasses for all config types (immutable after load)
- Atomic write pattern: temp file then os.rename

## Config Schema (TOML)
Three required sections: `[scan]`, `[state]`, `[agg.<name>]`.

Each `[agg.<name>]` block defines one aggregation type with its own `output_path`.
There is NO global `[output]` section -- output paths are per-agg-type.
Legacy `[output]` sections are rejected with a migration error.

Agg type identifiers: `qa`, `qm`, `snapshot` (not `sdd`).

## Conventions
- Config precedence: CLI flag > PYAGGREGATE_CONFIG env var > ./pyaggregate.toml
- Run ID defaults to today's ISO date
- Output directory layout: `<output_path>/<run_id>/<output_type>/<table>.parquet`
- Each run directory also contains `manifest.json` (per-run metadata: tables, columns, row counts, input provenance) and `run_summary.json`
- `latest` symlink managed atomically per agg type
- Exit codes: 0 = success, 1 = fatal, 2 = partial failure

## Boundaries
- Safe to edit: `src/`, `tests/`
- Immutable: `docs/implementation-plans/` (historical records)
