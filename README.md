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

See `docs/operations.md` for detailed operational documentation.
