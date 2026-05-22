# pyAggregate Operations Guide

This document describes how to operate, monitor, and maintain the pyAggregate system in production.

## Overview

pyAggregate is a scheduled aggregation pipeline for unified QA, QM, and SCDM Snapshot outputs. It is designed to run with minimal intervention once configured.

The system consists of:
- **Scanner**: Monitors the requests tree for new approved submissions and updates the catalog
- **Aggregator**: Processes catalog data and produces aggregated outputs
- **Writer**: Produces final output files and manages versioned snapshots

All components are orchestrated via CLI and are designed to be run by cron.

---

## Configuration File (pyaggregate.toml)

Before deploying, create a configuration file at a standard location (e.g., `/opt/pyaggregate/pyaggregate.toml`):

```toml
[scan]
requests_root = "/path/to/requests"

[state]
catalog_db = "/var/lib/pyaggregate/catalog.db"
log_dir = "/var/log/pyaggregate"

[agg.qa]
source_reqtype = "qar"
output_path = "/var/lib/pyaggregate/outputs/qa"
allowed_dpids = ["*"]

[agg.qm]
source_reqtype = "qmr"
output_path = "/var/lib/pyaggregate/outputs/qm"
allowed_dpids = ["*"]

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "/var/lib/pyaggregate/outputs/snapshot"
allowed_dpids = ["*"]
```

Each `[agg.*]` block requires `allowed_dpids` — a list of lowercase DPID strings controlling which data partners are included. Use `["*"]` for all. Unknown DPIDs (not found in catalog) produce warnings at run time but do not error.

---

## Cron Schedule

### Scanner (every 15 minutes)

```
*/15 * * * * flock -n /var/run/pyaggregate-scan.lock pyaggregate scan --config /opt/pyaggregate/pyaggregate.toml >> /var/log/pyaggregate/scan-cron.log 2>&1
```

**Explanation:**
- `flock -n`: Non-blocking file lock ensures only one scan runs at a time
- `scan` command: Walks the requests tree and updates the catalog
- Runs frequently to detect new submissions quickly
- **stderr redirect:** All output (JSON logs) goes to `scan-cron.log`

**Cron log format:**
Each run produces a single log file entry. Timestamp and all structured fields are in the JSON log at `log_dir/pyaggregate-YYYY-MM-DD.log`.

Scan captures all paths within the defined directory, allowing aggregation runs specifying different Data Partners to use a single database instance.

### Aggregation Run (weekly, early morning)

```
0 3 * * 0 pyaggregate run --config /opt/pyaggregate/pyaggregate.toml >> /var/log/pyaggregate/run-cron.log 2>&1
```

**Explanation:**
- Runs every Sunday at 3 AM
- Produces aggregated outputs for QA, QM, and SDDM
- Updates `latest` symlinks to point to the new run

**Alternative schedule** (if weekly is too frequent):
- Daily: `0 3 * * * pyaggregate run ...`
- Specific day: `0 3 * * 3` (Wednesday)

**Notes:**
- The `run` command is more resource-intensive than `scan`
- Tables are aggregated concurrently across CPU cores (thread pool)
- Allow 5-30 minutes for execution depending on data volume
- Schedule during off-peak hours to avoid impacting analysts

---

## State Directory Layout

The state directory (configured as `state.catalog_db` parent) contains:

```
/var/lib/pyaggregate/
├── catalog.db              # SQLite database of latest approved packages
├── catalog.db.bak          # Nightly backup (see "Backup Strategy")
└── outputs/
    ├── qa/
    │   ├── 2026-05-15/
    │   │   ├── stacked/
    │   │   │   ├── ae.parquet
    │   │   │   └── dem.parquet
    │   │   ├── masked/
    │   │   │   ├── ae.parquet
    │   │   │   └── dem.parquet
    │   │   ├── rollup/
    │   │   │   └── ae.parquet
    │   │   ├── dpid_map.csv
    │   │   ├── manifest.json
    │   │   └── run_summary.json
    │   ├── 2026-05-14/
    │   └── latest -> 2026-05-15
    ├── qm/
    │   ├── 2026-05-15/
    │   └── latest -> 2026-05-15
    └── snapshot/
        ├── 2026-05-15/
        └── latest -> 2026-05-15

/var/log/pyaggregate/
├── pyaggregate-2026-05-14.log     # JSON-lines structured logs
├── pyaggregate-2026-05-15.log
└── scan-cron.log                  # Cron stderr redirection (diagnostic)
```

**Key files:**

- **catalog.db**: Core state. Loss of this file requires re-scan from scratch.
- **latest symlinks**: Analysts use these to access current outputs. Updated atomically via temp-symlink-then-rename.
- **manifest.json**: Per-run metadata including table columns, row counts, and input provenance.
- **run_summary.json**: Exit code, timing, and skipped-table details for operators.
- **Staging directories**: During a write, files are assembled in `.tmp_<run_id>/` then atomically renamed to `<run_id>/`. If a `.tmp_*` directory remains after a run completes, it indicates an interrupted write.

---

## Backup Strategy

### Nightly Backup

Schedule a daily backup at a quiet time (e.g., 2 AM):

```bash
0 2 * * * cp /var/lib/pyaggregate/catalog.db /var/lib/pyaggregate/catalog.db.bak
```

Or with timestamp:
```bash
0 2 * * * cp /var/lib/pyaggregate/catalog.db /var/lib/pyaggregate/backups/catalog-$(date +\%Y-\%m-\%d).db.bak
```

### Backup Verification

After backup, verify the file:

```bash
# Check file size and timestamp
ls -lh /var/lib/pyaggregate/catalog.db.bak

# Verify database integrity
sqlite3 /var/lib/pyaggregate/catalog.db.bak "SELECT COUNT(*) FROM catalog;"
```

### Archival

For longer retention, copy to cold storage weekly:

```bash
0 3 * * 0 cp /var/lib/pyaggregate/catalog.db /archive/pyaggregate/catalog-$(date +\%Y-\%m-\%d).db
```

---

## Rollback Procedures

### Rollback to Previous Run

If a run produces unexpected outputs, revert the `latest` symlink:

```bash
# Identify the previous run
ls -l /var/lib/pyaggregate/outputs/qa/

# Example output:
# lrwxr-xr-x latest -> 2026-05-15-000001
# drwxr-xr-x 2026-05-15-000001
# drwxr-xr-x 2026-05-14-000001

# Rollback to the previous run
ln -sfn 2026-05-14-000001 /var/lib/pyaggregate/outputs/qa/latest
ln -sfn 2026-05-14-000001 /var/lib/pyaggregate/outputs/qm/latest
ln -sfn 2026-05-14-000001 /var/lib/pyaggregate/outputs/snapshot/latest
```

**Note:** The `-f` flag overwrites the current symlink atomically. Analysts querying the `latest` symlink will see the previous run immediately after the `ln` command completes.

### Rollback with Catalog Restore

If the catalog was corrupted:

```bash
# Restore the backup (from the previous night)
cp /var/lib/pyaggregate/catalog.db.bak /var/lib/pyaggregate/catalog.db

# Re-run the scanner to update the catalog
pyaggregate scan --config /opt/pyaggregate/pyaggregate.toml

# Re-run aggregation
pyaggregate run --config /opt/pyaggregate/pyaggregate.toml
```

---

## Log Inspection

### Real-time Log Monitoring

View JSON-formatted logs as they arrive:

```bash
# Watch today's log file
tail -f /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log

# Pretty-print JSON logs
tail -f /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log | jq .

# Filter logs by level
tail -f /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log | jq 'select(.level == "WARNING")'

# Filter logs by logger module
tail -f /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log | jq 'select(.logger == "pyaggregate.io.scanner")'
```

### Query Historical Logs

Extract specific log events from a previous day:

```bash
# Find all scan events
jq 'select(.logger == "pyaggregate.io.scanner")' /var/log/pyaggregate/pyaggregate-2026-05-14.log

# Find warnings and errors
jq 'select(.level == "WARNING" or .level == "ERROR")' /var/log/pyaggregate/pyaggregate-2026-05-14.log

# Extract row counts from aggregation runs
jq 'select(.message == "table aggregated") | {table: .table, stacked: .stacked_rows, masked: .masked_rows}' /var/log/pyaggregate/pyaggregate-2026-05-14.log

# Count events by type
jq -r '.message' /var/log/pyaggregate/pyaggregate-2026-05-14.log | sort | uniq -c
```

### Log Schema

Each JSON log line contains:

```json
{
  "timestamp": "2026-05-14T03:15:42.123456+00:00",
  "level": "INFO",
  "logger": "pyaggregate.io.scanner",
  "message": "scan started",
  "scan_id": "scan-20260514-031542",
  "extra_field": "value"
}
```

**Standard fields:**
- `timestamp`: UTC ISO 8601 format
- `level`: INFO, WARNING, ERROR, DEBUG
- `logger`: Python logger name (e.g., `pyaggregate.io.scanner`)
- `message`: Human-readable event description

**Dynamic fields** (depend on the event):
- `scan_id`: Identifier for a scanner run
- `table`: Table name (in aggregation context)
- `agg_type`: Aggregation type (qa, qm, snapshot)
- `dpid`: Data partner ID
- `run_id`: Identifier for an aggregation run
- `rows_upserted`, `packages_skipped`: Scanner statistics
- `stacked_rows`, `masked_rows`: Aggregation statistics

---

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Scanner health**
   - Exit code (should be 0 for success)
   - `scan started` and `scan complete` log entries appear within 15-minute window
   - `rows_upserted` and `packages_skipped` counts are reasonable

2. **Aggregation health**
   - Exit code (should be 0)
   - `run` command completes within expected time window (typically 5-30 min)
   - Row counts are reasonable (no sudden drops)

3. **Output freshness**
   - `latest` symlinks point to recent runs (not stale)
   - Summary files are recent

4. **Disk space**
   - Log files don't fill up disk (retention policy: keep 30 days)
   - Output files don't grow unexpectedly

### Alert Conditions

Set up alerting for:

**Critical (page on-call):**
- Scanner or aggregation exits with non-zero status
- Log file has `level: ERROR`
- Symlink is broken (points to non-existent directory)
- Disk usage exceeds 90%

**Warning (log for review):**
- Scanner or aggregation completes but has `WARNING` level entries
- Log file has `packages_skipped > 0` (indicates unparseable directories)
- Row counts drop significantly compared to previous run
- Last `scan complete` is older than 30 minutes

### Example: Alert on Scanner Failure

Using syslog and standard alerting:

```bash
# Extract scanner warnings/errors
jq 'select(.logger == "pyaggregate.io.scanner" and (.level == "ERROR" or .level == "WARNING"))' \
  /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log | \
  if grep -q .; then
    echo "Scanner errors detected" | \
      mail -s "pyAggregate Scanner Alert" ops@example.com
  fi
```

Or integrate with existing monitoring (Prometheus, Datadog, etc.) by parsing logs and emitting metrics.

### Example: Alert on Stale Latest Symlink

```bash
#!/bin/bash
# Check if latest symlink is older than 1 day

LATEST_PATH="/var/lib/pyaggregate/outputs/qa/latest"
THRESHOLD_SECONDS=$((24 * 3600))

if [ ! -L "$LATEST_PATH" ]; then
  echo "ERROR: $LATEST_PATH is not a symlink" >&2
  exit 1
fi

TARGET=$(readlink "$LATEST_PATH")
TARGET_DIR="/var/lib/pyaggregate/outputs/qa/$TARGET"

if [ ! -d "$TARGET_DIR" ]; then
  echo "ERROR: symlink target does not exist: $TARGET_DIR" >&2
  exit 1
fi

MTIME=$(stat -f %m "$TARGET_DIR" 2>/dev/null)
NOW=$(date +%s)
AGE=$((NOW - MTIME))

if [ "$AGE" -gt "$THRESHOLD_SECONDS" ]; then
  echo "WARNING: outputs are stale (age: $((AGE / 3600)) hours)" >&2
  exit 1
fi

echo "OK: outputs are current"
exit 0
```

---

## Maintenance Tasks

### Log Rotation

Logs accumulate daily. Set up rotation to prevent disk overflow:

```bash
# Create /etc/logrotate.d/pyaggregate
/var/log/pyaggregate/pyaggregate-*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0644 pyaggregate pyaggregate
    sharedscripts
}
```

### Catalog Maintenance

SQLite databases benefit from periodic optimization:

```bash
# Vacuum the catalog database (may take a few minutes)
sqlite3 /var/lib/pyaggregate/catalog.db "VACUUM;"

# Analyze statistics for query optimization
sqlite3 /var/lib/pyaggregate/catalog.db "ANALYZE;"
```

Schedule this during off-peak hours (e.g., late at night):

```bash
0 1 * * 0 sqlite3 /var/lib/pyaggregate/catalog.db "VACUUM; ANALYZE;"
```

### Output Directory Cleanup

Old output directories can accumulate. Archive or delete them periodically:

```bash
# List outputs older than 60 days
find /var/lib/pyaggregate/outputs -maxdepth 3 -type d -name "20??-??-??-??????" -mtime +60

# Archive to cold storage (don't delete, in case we need to audit)
find /var/lib/pyaggregate/outputs -maxdepth 3 -type d -name "20??-??-??-??????" -mtime +60 \
  -exec tar -czf /archive/pyaggregate/{} \; -delete
```

---

## Troubleshooting

### Scanner Hangs (Lock Contention)

If multiple scanner processes are running:

```bash
# Check for stale lock files
ls -l /var/run/pyaggregate-scan.lock

# Remove stale lock (only if sure no scan is running)
rm /var/run/pyaggregate-scan.lock
```

### Output Files Contain NaN or Invalid Data

Possible causes:
- Input data issue (check `dpid_map.csv` for rejected DPs)
- Schema mismatch (check summary.json for skipped tables)
- Numeric overflow (check logs for warnings)

**Investigation:**
```bash
# Inspect run_summary.json
jq . /var/lib/pyaggregate/outputs/qa/latest/run_summary.json

# Inspect manifest.json for row counts and column details
jq '.tables | to_entries[] | {table: .key, outputs: (.value.outputs | keys)}' \
  /var/lib/pyaggregate/outputs/qa/latest/manifest.json

# Check dpid_map.csv for rejected DPs
wc -l /var/lib/pyaggregate/outputs/qa/latest/dpid_map.csv
head -20 /var/lib/pyaggregate/outputs/qa/latest/dpid_map.csv

# Check logs for aggregation warnings
jq 'select(.logger == "pyaggregate.core.pipeline" and .level == "WARNING")' \
  /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log
```

### "Disk full" Error During Run

Check available space:

```bash
df -h /var/lib/pyaggregate/

# Estimate size of outputs
du -sh /var/lib/pyaggregate/outputs/
```

**Cleanup:**
- Delete old output directories (see "Output Directory Cleanup")
- Delete old log files (logrotate handles this automatically)
- Check for leftover `.tmp_*` staging directories and remove them

### Scanner Detects Many "Unparseable" Directories

Check logs:

```bash
jq 'select(.message == "unparseable package directory")' \
  /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log
```

Common causes:
- Wrong directory structure (check requests tree layout)
- Missing `msoc/` subdirectory in packages
- Wrong file naming convention

---

## Emergency Contacts

- **Ops Team**: ops@example.com
- **Data Engineering**: data-eng@example.com
- **SAS Program Maintainers**: sas-maintainers@example.com (during transition period)

---

## Summary

pyAggregate is designed to run automatically. Operators should:
1. Set up cron jobs for scanner and aggregation runs
2. Monitor logs for errors and warnings
3. Ensure backups run nightly and are verified
4. Check symlinks and outputs periodically for freshness
5. Rotate logs to prevent disk overflow
6. Perform rollback if unexpected outputs are detected
