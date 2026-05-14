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
pyaggregate init-db

# Scan for latest approved submissions
pyaggregate scan

# Run all aggregations (qa, qm, sdd)
pyaggregate run

# Run a single aggregation type
pyaggregate run --type qa

# Inspect state
pyaggregate show-catalog
pyaggregate show-dpid-map
pyaggregate show-scans
```

## Operational model

Two cron jobs cover the full lifecycle:

- `*/15 * * * * flock -n /var/run/pyaggregate-scan.lock pyaggregate scan` — scan every 15 minutes
- `0 3 * * 0 pyaggregate run` — aggregate weekly

See `docs/operations.md` for detailed operational documentation.
