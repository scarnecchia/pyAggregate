# pyAggregate Migration Guide

This document describes how to migrate from the legacy SAS-based aggregation system to pyAggregate. It covers parity verification, parallel testing, and the retirement checklist.

## Overview

The SAS aggregation system (QAR/QMR aggregation) will be replaced by pyAggregate. This migration requires:
1. **Parity verification**: Ensure pyAggregate outputs match SAS outputs
2. **Shadow run period**: Run both systems in parallel for 2 weeks
3. **Cutover**: Switch production to pyAggregate
4. **SAS retirement**: Archive legacy SAS programs

---

## Phase 1: Parity Verification (Week 1)

### 1.1 Prepare Test Environment

Set up a test configuration that mirrors production but uses recent input data:

```bash
# Create test config
mkdir -p /tmp/pyaggregate-test
cat > /tmp/pyaggregate-test/pyaggregate.toml <<EOF
[scan]
requests_root = "/path/to/requests"

[state]
catalog_db = "/tmp/pyaggregate-test/catalog.db"
log_dir = "/tmp/pyaggregate-test/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "/tmp/pyaggregate-test/outputs/qa"

[agg.qm]
source_reqtype = "qmr"
output_path = "/tmp/pyaggregate-test/outputs/qm"

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "/tmp/pyaggregate-test/outputs/snapshot"
EOF
```

### 1.2 Run Baseline SAS Job

Execute the most recent production SAS job to capture baseline outputs:

```bash
# Example (adjust for actual SAS system)
cd /path/to/sas/programs
sas -batch -config sas-config.xml run_aggregation.sas

# Capture outputs
cp -r /output/sas/qa/latest /tmp/baseline-qa-latest
cp -r /output/sas/qm/latest /tmp/baseline-qm-latest
cp -r /output/sas/snapshot/latest /tmp/baseline-snapshot-latest

# Note the run ID and timestamp
ls -l /tmp/baseline-qa-latest/
```

### 1.3 Run pyAggregate on Same Input Data

Initialize and run pyAggregate against the same requests tree:

```bash
# Initialize database
pyaggregate init-db --config /tmp/pyaggregate-test/pyaggregate.toml

# Scan the requests tree
pyaggregate scan --config /tmp/pyaggregate-test/pyaggregate.toml

# Run aggregation
pyaggregate run --config /tmp/pyaggregate-test/pyaggregate.toml

# Note the run ID
ls -l /tmp/pyaggregate-test/outputs/qa/
```

### 1.4 Compare Output Schema

Check that column names, types, and order match:

```bash
# Using Python/pandas
python3 << 'PYTHON'
import pandas as pd
import json

# Load baseline SAS output
sas_qa = pd.read_parquet("/tmp/baseline-qa-latest/ae.parquet")

# Load pyAggregate output
pya_qa = pd.read_parquet("/tmp/pyaggregate-test/outputs/qa/latest/ae.parquet")

# Compare schemas
print("=== SAS Schema ===")
print(sas_qa.dtypes)

print("\n=== pyAggregate Schema ===")
print(pya_qa.dtypes)

# Check for schema differences
sas_cols = set(sas_qa.columns)
pya_cols = set(pya_qa.columns)

if sas_cols != pya_cols:
    print(f"\nColumn mismatch!")
    print(f"In SAS but not pyAgg: {sas_cols - pya_cols}")
    print(f"In pyAgg but not SAS: {pya_cols - sas_cols}")
else:
    print("\nSchemas match!")

# Check dtypes
for col in sas_qa.columns:
    if sas_qa[col].dtype != pya_qa[col].dtype:
        print(f"Type mismatch in {col}: SAS={sas_qa[col].dtype} vs pyAgg={pya_qa[col].dtype}")
PYTHON
```

### 1.5 Compare Row Counts

Verify that the number of rows in each aggregation level matches:

```bash
# Using Python
python3 << 'PYTHON'
import pandas as pd

tables = ["ae", "dem", "lab", "vital"]

for table in tables:
    try:
        sas_df = pd.read_parquet(f"/tmp/baseline-qa-latest/{table}.parquet")
        pya_df = pd.read_parquet(f"/tmp/pyaggregate-test/outputs/qa/latest/{table}.parquet")
        
        sas_rows = len(sas_df)
        pya_rows = len(pya_df)
        
        match = "✓" if sas_rows == pya_rows else "✗"
        print(f"{match} {table}: SAS={sas_rows:,} vs pyAgg={pya_rows:,}")
        
        if sas_rows != pya_rows:
            diff = pya_rows - sas_rows
            pct = 100.0 * diff / sas_rows
            print(f"   Difference: {diff:+,} ({pct:+.2f}%)")
    except FileNotFoundError:
        print(f"  {table}: File not found (expected if table not in aggregation)")
PYTHON
```

**Expected result:** All row counts should match exactly (0% difference) for baseline comparison.

### 1.6 Compare Numeric Values

Verify that numeric aggregations (sums, counts, means) are identical:

```bash
# Using Python (example for QA aggregation)
python3 << 'PYTHON'
import pandas as pd
import numpy as np

sas_df = pd.read_parquet("/tmp/baseline-qa-latest/ae.parquet")
pya_df = pd.read_parquet("/tmp/pyaggregate-test/outputs/qa/latest/ae.parquet")

# Sort both by DPID and internal key to ensure alignment
key_cols = [c for c in sas_df.columns if c.startswith(("SURR", "DPID"))]
if not key_cols:
    key_cols = ["DPID"]

sas_sorted = sas_df.sort_values(by=key_cols).reset_index(drop=True)
pya_sorted = pya_df.sort_values(by=key_cols).reset_index(drop=True)

# Compare numeric columns
numeric_cols = sas_sorted.select_dtypes(include=[np.number]).columns

mismatches = []
for col in numeric_cols:
    if not np.allclose(sas_sorted[col].fillna(0), pya_sorted[col].fillna(0), rtol=1e-9):
        # Calculate per-row differences
        diff = abs(sas_sorted[col] - pya_sorted[col])
        max_diff = diff.max()
        mean_diff = diff.mean()
        
        mismatches.append({
            "column": col,
            "max_diff": max_diff,
            "mean_diff": mean_diff
        })

if mismatches:
    print("Numeric mismatches found:")
    for m in mismatches:
        print(f"  {m['column']}: max={m['max_diff']}, mean={m['mean_diff']}")
else:
    print("All numeric columns match!")
PYTHON
```

**Known acceptable differences:**
- Floating-point precision: < 1e-6
- Date formatting: If SAS uses SAS date format and pyAgg uses ISO 8601, dates must be converted for comparison
- Column order: Can be reordered in post-processing

### 1.7 Reconciliation: Known Discrepancies

Document and reconcile any differences:

#### Date Format Handling

If SAS outputs SAS date format (numeric, days since 1960-01-01) and pyAggregate outputs ISO 8601 strings:

```python
from datetime import datetime, timedelta

def sas_date_to_iso(sas_date):
    """Convert SAS date numeric to ISO 8601 string."""
    sas_epoch = datetime(1960, 1, 1)
    return (sas_epoch + timedelta(days=int(sas_date))).isoformat()

# Convert SAS dates for comparison
sas_dates = sas_df["DATE_COL"].apply(sas_date_to_iso)
if sas_dates.equals(pya_df["DATE_COL"]):
    print("Date columns match after format conversion")
```

#### Column Ordering

pyAggregate may output columns in a different order than SAS. This is acceptable if all columns are present:

```python
# Check that all columns are present (order doesn't matter)
sas_cols = set(sas_df.columns)
pya_cols = set(pya_df.columns)

if sas_cols == pya_cols:
    print("All columns present (order may differ)")
else:
    print(f"Column mismatch: {sas_cols ^ pya_cols}")
```

#### Null/Missing Value Handling

SAS may represent missing values differently than pandas (e.g., ".C" vs NaN):

```python
# Check for NaN/null mismatches
sas_nulls = sas_df.isna().sum().sum()
pya_nulls = pya_df.isna().sum().sum()

if sas_nulls != pya_nulls:
    print(f"Null count mismatch: SAS={sas_nulls}, pyAgg={pya_nulls}")
    
    # Investigate which columns differ
    for col in sas_df.columns:
        if sas_df[col].isna().sum() != pya_df[col].isna().sum():
            print(f"  {col}: SAS={sas_df[col].isna().sum()}, pyAgg={pya_df[col].isna().sum()}")
```

#### Row Count Discrepancies

Small row count differences may be acceptable if due to known data handling differences:

- **Excluded DPs**: If SAS excludes certain data partners due to quality flags, pyAggregate should use the same logic
- **Date range**: Ensure both SAS and pyAggregate use the same lookback period
- **Duplicate handling**: Verify duplicate detection logic is consistent

**Resolution:**
1. Identify the source of the discrepancy (log inspection)
2. Document the reason (e.g., "SAS excludes DP XYZ due to quality flag")
3. Verify the difference is acceptable to stakeholders
4. Update configuration or code if needed

### 1.8 Parity Verification Checklist

- [ ] Schemas match (same columns, same data types)
- [ ] Row counts match exactly (or documented difference is acceptable)
- [ ] Numeric values match (within 1e-6 for floating-point)
- [ ] Summary statistics match (min, max, mean, sum)
- [ ] All three agg types (QA, QM, SDD) are consistent
- [ ] Run completed without errors (check exit code and logs)
- [ ] dpid_map.csv contains all expected data partners
- [ ] No `.tmp` files left behind

**If all checks pass**, proceed to Phase 2.

**If any checks fail**, investigate:
1. Check pyaggregate logs for errors or warnings
2. Verify input data is identical (same requests tree)
3. Run diagnostic queries (see "Troubleshooting" section)
4. Escalate to Data Engineering team

---

## Phase 2: Shadow Run Period (2 Weeks)

### 2.1 Set Up Parallel Running

Configure pyAggregate to run alongside the production SAS job:

```bash
# Add pyAggregate run to production schedule
# Schedule it to run AFTER the SAS job completes

# Production crontab (example)
# SAS job: 0 3 * * 0 /path/to/sas/run_aggregation.sh
# pyAgg: 30 3 * * 0 pyaggregate run --config /opt/pyaggregate/pyaggregate.toml

# Log both to the same monitoring system
```

### 2.2 Daily Verification Script

Create a script to automatically verify outputs:

```bash
#!/bin/bash
# daily-verify.sh

set -e

CONFIG_PATH="/opt/pyaggregate/pyaggregate.toml"
LOG_EMAIL="ops@example.com"

# Get today's run directories
SAS_RUN=$(ls -trd /output/sas/qa/latest/ | head -1)
PYA_RUN=$(ls -trd /var/lib/pyaggregate/outputs/qa/latest/ | head -1)

# Compare row counts for all tables
DIFFERENCES=""

for TABLE in ae dem lab vital; do
  SAS_ROWS=$(python3 -c "import pandas as pd; print(len(pd.read_parquet('$SAS_RUN/$TABLE.parquet')))" 2>/dev/null || echo "NOTFOUND")
  PYA_ROWS=$(python3 -c "import pandas as pd; print(len(pd.read_parquet('$PYA_RUN/$TABLE.parquet')))" 2>/dev/null || echo "NOTFOUND")
  
  if [ "$SAS_ROWS" != "$PYA_ROWS" ]; then
    DIFFERENCES="${DIFFERENCES}${TABLE}: SAS=$SAS_ROWS, pyAgg=$PYA_ROWS\n"
  fi
done

if [ -n "$DIFFERENCES" ]; then
  echo -e "Row count differences detected:\n$DIFFERENCES" | \
    mail -s "pyAggregate Shadow Run Alert: Row Differences" "$LOG_EMAIL"
fi

# Check pyaggregate logs for errors
if grep -q '"level": "ERROR"' /var/log/pyaggregate/pyaggregate-$(date +%Y-%m-%d).log; then
  echo "pyAggregate errors detected. Check /var/log/pyaggregate/" | \
    mail -s "pyAggregate Shadow Run Alert: Errors" "$LOG_EMAIL"
fi

echo "Daily verification complete"
```

Schedule it:
```bash
0 6 * * * /opt/pyaggregate/scripts/daily-verify.sh
```

### 2.3 Weekly Summary Report

Generate a weekly report comparing outputs:

```bash
#!/bin/bash
# weekly-summary.sh

REPORT_FILE="/tmp/pyaggregate-weekly-summary.txt"

cat > "$REPORT_FILE" << 'EOF'
# pyAggregate Shadow Run Summary Report

## Row Count Comparison (Last 7 Days)
EOF

# Get last 7 days of runs
python3 << 'PYTHON'
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sas_root = Path("/output/sas/qa")
pya_root = Path("/var/lib/pyaggregate/outputs/qa")

print("| Date | Table | SAS Rows | pyAgg Rows | Match |")
print("|------|-------|----------|------------|-------|")

for i in range(7):
    date = datetime.now() - timedelta(days=i)
    date_str = date.strftime("%Y-%m-%d")
    
    # Find run directories for this date (could be multiple runs per day)
    sas_runs = sorted([d for d in sas_root.iterdir() if d.is_dir() and date_str in d.name], reverse=True)
    pya_runs = sorted([d for d in pya_root.iterdir() if d.is_dir() and date_str in d.name], reverse=True)
    
    if not sas_runs or not pya_runs:
        continue
    
    sas_run = sas_runs[0]
    pya_run = pya_runs[0]
    
    for table in ["ae", "dem", "lab", "vital"]:
        sas_file = sas_run / f"{table}.parquet"
        pya_file = pya_run / f"{table}.parquet"
        
        if sas_file.exists() and pya_file.exists():
            sas_rows = len(pd.read_parquet(sas_file))
            pya_rows = len(pd.read_parquet(pya_file))
            match = "✓" if sas_rows == pya_rows else "✗"
            print(f"| {date_str} | {table} | {sas_rows:,} | {pya_rows:,} | {match} |")
PYTHON

cat >> "$REPORT_FILE" << 'EOF'

## Errors and Warnings

EOF

# Append error summary
jq -r 'select(.level == "ERROR") | "\(.timestamp): \(.logger): \(.message)"' \
  /var/log/pyaggregate/pyaggregate-*.log >> "$REPORT_FILE" 2>/dev/null || echo "No errors" >> "$REPORT_FILE"

# Email the report
mail -s "pyAggregate Shadow Run Weekly Summary" ops@example.com < "$REPORT_FILE"
```

Schedule it:
```bash
0 7 * * 1 /opt/pyaggregate/scripts/weekly-summary.sh
```

### 2.4 Review Checklist (Weekly)

Each week during the shadow run period:

- [ ] No error-level logs in pyaggregate
- [ ] Row counts match SAS outputs (or documented acceptable differences)
- [ ] pyAggregate runs complete within SLA (expected time window)
- [ ] Symlinks are current (not stale)
- [ ] Disk usage is within expected bounds
- [ ] No crashes or unexpected exits

### 2.5 Stakeholder Briefing

At the end of Week 1 and Week 2:
- Review parity results with analysts
- Confirm acceptable discrepancies are documented
- Address any concerns or questions
- Obtain sign-off before proceeding to cutover

---

## Phase 3: Cutover (Week 3)

### 3.1 Pre-Cutover Checklist

Before switching production to pyAggregate:

- [ ] Data Engineering team has reviewed parity results
- [ ] Analysts have reviewed outputs and confirmed acceptability
- [ ] All 14 days of shadow run comparisons are documented
- [ ] No critical issues remain
- [ ] Backup and rollback procedures are tested
- [ ] Operations team is trained on pyAggregate operations
- [ ] Monitoring and alerting are in place
- [ ] Emergency contacts and escalation procedures are documented

### 3.2 Cutover Window

Schedule the cutover during a planned maintenance window:

```bash
# 1. Stop the production SAS job (or rename cron entry)
# Example: comment out or rename the SAS job in crontab

# 2. Verify latest pyAggregate output is fresh and correct
ls -l /var/lib/pyaggregate/outputs/qa/latest/
jq . /var/lib/pyaggregate/outputs/qa/latest/summary.json

# 3. Update analyst access paths (if they have hardcoded paths)
# Example: if analysts reference /output/sas/qa/latest, 
# update to /var/lib/pyaggregate/outputs/qa/latest or create symlinks

# 4. Enable production pyAggregate cron job
# Example: uncomment pyAggregate schedule in crontab

# 5. Send notification to stakeholders
mail -s "pyAggregate Cutover Complete" analysts@example.com << 'EOF'
The aggregation pipeline has been switched to pyAggregate.

QA outputs: /var/lib/pyaggregate/outputs/qa/latest/
QM outputs: /var/lib/pyaggregate/outputs/qm/latest/
Snapshot outputs: /var/lib/pyaggregate/outputs/snapshot/latest/

Contact ops@example.com if you encounter any issues.
EOF
```

### 3.3 Post-Cutover Monitoring (First Week)

Close monitoring during the first week after cutover:

- Daily verification script runs automatically
- Ops team reviews logs daily
- Escalation ready for immediate issues
- Analysts report any anomalies immediately

### 3.4 Rollback Plan

If critical issues are discovered:

```bash
# 1. Revert to SAS job in crontab (uncomment SAS job, comment pyAgg)

# 2. Update analyst paths to point to SAS outputs
# Example: ln -sfn /output/sas/qa/latest /var/lib/pyaggregate/outputs/qa/rollback-to-sas

# 3. Investigate pyAggregate issue (don't delete logs or outputs)

# 4. Contact Data Engineering team
```

**Note:** Rollback should take < 10 minutes. Test the rollback procedure before cutover.

---

## Phase 4: SAS Program Retirement (Week 4+)

### 4.1 SAS Program Archival

After 4 weeks of stable production with pyAggregate:

```bash
# 1. Create archive directory
mkdir -p /archive/sas-programs/2026-05-14-retirement

# 2. Copy all SAS source code and metadata
cp -r /path/to/sas/programs /archive/sas-programs/2026-05-14-retirement/
cp -r /path/to/sas/config /archive/sas-programs/2026-05-14-retirement/
cp -r /path/to/sas/logs /archive/sas-programs/2026-05-14-retirement/

# 3. Document the SAS system in an archive README
cat > /archive/sas-programs/2026-05-14-retirement/README.md << 'EOF'
# Legacy SAS Aggregation System - Archived

Retired: 2026-05-14
Replacement: pyAggregate

This directory contains the source code and documentation of the legacy
SAS-based aggregation system for QA/QM outputs. This system was replaced
by pyAggregate in May 2026.

Files:
- programs/: SAS source code
- config/: SAS configuration files
- logs/: Historical logs from the last 30 days of operation

Parity Verification:
- All outputs were verified to match pyAggregate outputs
- 14-day shadow run period with no critical discrepancies
- Cutover completed successfully

For historical analysis or audit purposes, consult the archive logs
or contact the original SAS program maintainers.

Contacts:
- Current SAS Maintainer: [Name]
- pyAggregate Owner: [Name]
EOF

# 4. Calculate final checksums
sha256sum /archive/sas-programs/2026-05-14-retirement/* > /archive/sas-programs/2026-05-14-retirement/CHECKSUMS.txt

echo "Archive complete. SAS programs archived to /archive/sas-programs/2026-05-14-retirement/"
```

### 4.2 Remove SAS Cron Jobs

After archival, remove the SAS job from production:

```bash
# 1. Verify pyAggregate is running smoothly
# (Already covered in post-cutover monitoring)

# 2. Remove SAS cron entry
# Edit /etc/cron.d/sas-aggregation or user crontab
# Comment out or delete the SAS job entry

# 3. Delete SAS program directories (optional; only after long-term archival)
# rm -rf /path/to/sas/programs

# 4. Document the retirement
cat >> /archive/sas-programs/2026-05-14-retirement/RETIREMENT.log << 'EOF'
2026-05-28: SAS cron jobs removed from production
2026-05-28: pyAggregate fully operational for 4 weeks without critical issues
2026-05-28: System marked as stable; legacy SAS system retired
EOF
```

### 4.3 Decommissioning Checklist

- [ ] All SAS source code archived and checksummed
- [ ] All SAS logs backed up
- [ ] Analysts have been notified of retirement
- [ ] Documentation has been updated
- [ ] SAS cron jobs removed
- [ ] SAS environment variables cleaned up
- [ ] SAS licenses deactivated (if applicable)
- [ ] Team training completed on pyAggregate operations

### 4.4 Documentation Updates

Update project documentation to remove any SAS-related procedures:

```bash
# Update README or operations manual
# Remove references to SAS programs
# Add links to pyAggregate documentation
# Update run-book with new troubleshooting procedures
```

---

## Migration Verification Checklist

### Phase 1: Parity Verification
- [ ] Baseline SAS run executed
- [ ] pyAggregate run executed on same input data
- [ ] Schemas match (same columns, data types)
- [ ] Row counts verified (per table, per agg type)
- [ ] Numeric values match (within acceptable tolerance)
- [ ] Summary statistics validated
- [ ] Known discrepancies documented and approved
- [ ] Data Engineering sign-off obtained

### Phase 2: Shadow Run
- [ ] Parallel runs set up (SAS + pyAggregate)
- [ ] Daily verification script running
- [ ] Weekly summary reports generated
- [ ] 14 days of successful shadow runs completed
- [ ] No critical issues discovered
- [ ] Analysts review outputs and confirm acceptability
- [ ] Stakeholder sign-off obtained

### Phase 3: Cutover
- [ ] Pre-cutover checklist completed
- [ ] Cutover executed during maintenance window
- [ ] Analyst access paths updated
- [ ] Notifications sent to stakeholders
- [ ] First-week monitoring plan active
- [ ] No critical issues discovered post-cutover
- [ ] Operations team confirms stability

### Phase 4: SAS Retirement
- [ ] 4+ weeks of stable production operation
- [ ] SAS programs archived and checksummed
- [ ] Backup copies verified
- [ ] SAS cron jobs removed
- [ ] Licensing and access deactivated
- [ ] Team trained on new system
- [ ] Documentation updated
- [ ] Archive location documented for future reference

---

## Troubleshooting During Migration

### Row Count Mismatch

**Problem:** pyAggregate outputs have different row counts than SAS.

**Investigation:**
1. Check pyaggregate logs for warnings:
   ```bash
   jq 'select(.level == "WARNING")' /var/log/pyaggregate/pyaggregate-*.log | jq -s 'group_by(.message) | map({message: .[0].message, count: length})'
   ```

2. Compare dpid_map.csv:
   ```bash
   diff /tmp/baseline-qa-latest/dpid_map.csv /tmp/pyaggregate-test/outputs/qa/latest/dpid_map.csv
   ```

3. Inspect summary.json:
   ```bash
   jq . /tmp/pyaggregate-test/outputs/qa/latest/summary.json | grep -A5 skipped
   ```

**Common causes:**
- Different input data (verify requests tree is identical)
- Excluded data partners (verify exclusion logic matches)
- Different date ranges (verify lookback period matches)

### Numeric Value Differences

**Problem:** Column values differ between SAS and pyAggregate (e.g., sums, counts).

**Investigation:**
1. Check for rounding differences:
   ```bash
   python3 << 'PYTHON'
   import pandas as pd
   import numpy as np
   sas = pd.read_parquet("/tmp/baseline-qa-latest/ae.parquet")
   pya = pd.read_parquet("/tmp/pyaggregate-test/outputs/qa/latest/ae.parquet")
   
   # Check columns with numeric values
   for col in sas.select_dtypes(include=[np.number]).columns:
       rel_error = (abs(sas[col] - pya[col]) / (abs(sas[col]) + 1e-10)).max()
       if rel_error > 1e-6:
           print(f"{col}: max relative error = {rel_error}")
   PYTHON
   ```

2. Check pyaggregate logs for rollup issues:
   ```bash
   jq 'select(.message contains "rollup")' /var/log/pyaggregate/pyaggregate-*.log
   ```

**Common causes:**
- Different aggregation logic (check rollup_aggs configuration)
- Rounding differences (expected; document as acceptable)
- Different null handling (check exclude_from_rollup patterns)

### Analyzer/File Not Found

**Problem:** pyAggregate can't find input files.

**Investigation:**
1. Verify requests tree structure:
   ```bash
   find /path/to/requests -type f -name "*.sas7bdat" | head -20
   ```

2. Check scanner logs:
   ```bash
   jq 'select(.logger == "pyaggregate.io.scanner")' /var/log/pyaggregate/pyaggregate-*.log
   ```

**Common causes:**
- Requests tree path is wrong (verify in config file)
- Data partner directory structure doesn't match expectations
- SAS files are missing (check with SAS team)

---

## Success Criteria

The migration is complete when:

1. **Parity verified**: All outputs match SAS baseline (within acceptable tolerance)
2. **Shadow run stable**: 14 days of parallel operation with no critical issues
3. **Stakeholder approved**: Analysts and managers have signed off
4. **Production stable**: 4+ weeks of pyAggregate in production with no issues
5. **SAS archived**: Legacy system documented and safely archived
6. **Team trained**: Operations and analysts are confident with new system

---

## Post-Migration Maintenance

After successful migration:

1. **Monitor pyAggregate daily**: Check logs for errors and warnings
2. **Keep SAS archive safe**: Store in secure, backed-up location
3. **Update runbooks**: Document only pyAggregate procedures
4. **Train new team members**: Ensure all operators know pyAggregate
5. **Archive old outputs**: Move ancient SAS outputs to cold storage periodically

---

## Questions or Issues?

Contact the Data Engineering team for:
- Migration timeline questions
- Technical issues during parity verification
- Discrepancy reconciliation
- Escalation during cutover
