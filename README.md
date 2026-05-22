# pyaggregate

Unified QA, QM, and SCDM Snapshot aggregation CLI. Replaces the legacy SAS-based QA Aggregation and SCDM Snapshot Aggregation batch programs.

## Install

```bash
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
pre-commit install
```

## Usage

```bash
# Initialize the catalog database
pyaggregate init-db --config /path/to/pyaggregate.toml

# Scan for latest approved submissions
pyaggregate scan
pyaggregate scan --dry-run   # preview changes without modifying catalog

# Run all aggregations (qa, qm, snapshot)
pyaggregate run

# Run a single aggregation type
pyaggregate run --type qa

# Re-run over an existing run directory
pyaggregate run --force

# Inspect state
pyaggregate show-catalog
pyaggregate show-dpid-map
pyaggregate show-scans
```

Config resolution: `--config` flag > `PYAGGREGATE_CONFIG` env var > `./pyaggregate.toml`.

Tables are aggregated concurrently across CPU cores. Each run directory is written atomically via a staging directory — consumers never see partial outputs.

## Configuration

Each aggregation type requires an `allowed_dpids` list controlling which data partners are included. Use `["*"]` for all:

```toml
[agg.qa]
source_reqtype = "qar"
output_path = "/var/lib/pyaggregate/outputs/qa"
allowed_dpids = ["*"]

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "/var/lib/pyaggregate/outputs/snapshot"
allowed_dpids = ["aeos", "cms", "kpsc"]
```

See `pyaggregate.example.toml` for the full reference config.

## Output layout

Each run produces:

```
<output_path>/<run_id>/
├── stacked/<table>.parquet     # all DPs concatenated, real dpid column
├── masked/<table>.parquet      # dpid replaced with surrogate_id
├── rollup/<table>.parquet      # aggregated (excluded tables omitted)
├── dpid_map.csv                # surrogate mapping (filtered to this run)
├── manifest.json               # per-file metadata and input provenance
└── run_summary.json            # exit code, timing, skipped tables
```

A `latest` symlink at `<output_path>/latest` points to the most recent run.

## Operational model

Two cron jobs cover the full lifecycle:

- `*/15 * * * * flock -n /var/run/pyaggregate-scan.lock pyaggregate scan` — scan every 15 minutes
- `0 3 * * 0 pyaggregate run` — aggregate weekly

See [docs/operations.md](docs/operations.md) for detailed operational documentation, and [docs/migration.md](docs/migration.md) for migrating from the legacy SAS pipeline.

## Development

Requirements: Python 3.11+.

Set up a working copy with dev dependencies and pre-commit hooks:

```bash
pip install -e ".[dev]"
pre-commit install
```

### Project layout

- [src/pyaggregate/cli.py](src/pyaggregate/cli.py) — Typer CLI entry point (imperative shell)
- [src/pyaggregate/config.py](src/pyaggregate/config.py) — TOML loader and frozen config dataclasses
- [src/pyaggregate/core/](src/pyaggregate/core/) — pure domain logic (pipeline, input resolution, masking)
- [src/pyaggregate/io/](src/pyaggregate/io/) — I/O adapters (writer, scanner, catalog store, SAS reader)
- [tests/](tests/) — pytest + Hypothesis test suite
- [docs/](docs/) — operations and migration guides
- [pyaggregate.example.toml](pyaggregate.example.toml) — reference config

The codebase follows a Functional Core / Imperative Shell pattern; files are annotated with `# pattern:` comments indicating which side of the boundary they live on. Config dataclasses are frozen, and run outputs are written via a temp-then-rename atomic pattern.

### Common tasks

```bash
pytest                        # run the test suite
ruff check src/ tests/        # lint
mypy src/                     # type check
```

### Running locally

Point the CLI at a local config (e.g. a copy of `pyaggregate.example.toml`) via `--config`, the `PYAGGREGATE_CONFIG` env var, or by placing `pyaggregate.toml` in the working directory — resolution follows that precedence order.

```bash
pyaggregate init-db --config ./pyaggregate.toml
pyaggregate scan   --config ./pyaggregate.toml
pyaggregate run    --config ./pyaggregate.toml
```

### Further reading

- [docs/operations.md](docs/operations.md) — cron schedule, state layout, backups, monitoring, log inspection, troubleshooting
- [docs/migration.md](docs/migration.md) — parity verification, shadow run, cutover, and SAS retirement procedures
