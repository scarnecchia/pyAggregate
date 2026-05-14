# pattern: Imperative Shell
"""Output writer for aggregation results."""

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def write_run(
    output_root: Path,
    agg_type: str,
    run_id: str,
    table_outputs: dict[str, dict[str, pl.DataFrame]],
    dpid_map_frame: pl.DataFrame,
    update_latest: bool,
) -> None:
    """Write aggregation outputs to disk with atomic temp-rename pattern.

    Writes parquet files to output_root/<agg_type>/<run_id>/<output_type>/
    using temp-then-rename for atomicity. Creates dpid_map.csv filtered to
    surrogates actually used in masked outputs. Manages latest symlink atomically.

    Args:
        output_root: Root directory for outputs
        agg_type: Aggregation type (qa, qm, sdd)
        run_id: Run identifier (directory name)
        table_outputs: Dict mapping table_name -> {output_type -> DataFrame}
        dpid_map_frame: Full dpid_map DataFrame to filter
        update_latest: Whether to update the latest symlink
    """
    run_dir = output_root / agg_type / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Clean up orphaned .tmp files from previous interrupted runs
    for tmp_file in run_dir.rglob("*.tmp"):
        logger.info(f"Removing orphaned tmp file: {tmp_file}")
        tmp_file.unlink()

    started_at = datetime.now(UTC).isoformat()
    tables_succeeded: list[str] = []
    tables_skipped: list[dict] = []

    # Write parquet files for each table and output type
    for table_name, outputs_dict in table_outputs.items():
        try:
            for output_type, df in outputs_dict.items():
                output_dir = run_dir / output_type
                output_dir.mkdir(parents=True, exist_ok=True)

                parquet_file = output_dir / f"{table_name}.parquet"
                tmp_file = output_dir / f"{table_name}.parquet.tmp"

                # Write to temp file first
                df.write_parquet(str(tmp_file))

                # Atomic rename
                os.rename(str(tmp_file), str(parquet_file))

            tables_succeeded.append(table_name)
        except Exception as e:
            logger.error(f"Failed to write table {table_name}: {e}", exc_info=True)
            tables_skipped.append({
                "table": table_name,
                "error_class": "write_error",
                "detail": str(e),
            })

    # Filter dpid_map to only surrogates actually used in masked outputs
    masked_surrogates: set[str] = set()
    for table_name, outputs_dict in table_outputs.items():
        if "masked" in outputs_dict:
            masked_df = outputs_dict["masked"]
            if "surrogate_id" in masked_df.columns:
                surrogates = masked_df.get_column("surrogate_id").unique().to_list()
                masked_surrogates.update(s for s in surrogates if s is not None)

    # Filter dpid_map to only include used surrogates
    if masked_surrogates:
        filtered_map = dpid_map_frame.filter(
            pl.col("surrogate_id").is_in(list(masked_surrogates))
        )
    else:
        filtered_map = pl.DataFrame(columns=dpid_map_frame.columns)

    # Write dpid_map.csv via temp-then-rename
    dpid_map_path = run_dir / "dpid_map.csv"
    dpid_map_tmp = run_dir / "dpid_map.csv.tmp"
    filtered_map.write_csv(str(dpid_map_tmp))
    os.rename(str(dpid_map_tmp), str(dpid_map_path))

    # Write run_summary.json
    ended_at = datetime.now(UTC).isoformat()
    exit_code = 0 if not tables_skipped else 2

    summary = {
        "run_id": run_id,
        "agg_type": agg_type,
        "started_at": started_at,
        "ended_at": ended_at,
        "tables_succeeded": tables_succeeded,
        "tables_skipped": tables_skipped,
        "exit_code": exit_code,
    }

    summary_path = run_dir / "run_summary.json"
    summary_tmp = run_dir / "run_summary.json.tmp"
    with open(summary_tmp, "w") as f:
        json.dump(summary, f, indent=2)
    os.rename(str(summary_tmp), str(summary_path))

    # Update latest symlink if requested
    if update_latest:
        latest_dir = output_root / agg_type
        latest_path = latest_dir / "latest"
        latest_tmp = latest_dir / f"latest.{tempfile.gettempprefix()}{os.getpid()}"

        # Create symlink to temp name (relative path to run_id)
        os.symlink(run_id, str(latest_tmp))

        # Atomic rename to final path
        os.rename(str(latest_tmp), str(latest_path))


def check_run_exists(output_root: Path, agg_type: str, run_id: str) -> bool:
    """Check if a run directory already exists.

    Args:
        output_root: Root directory for outputs
        agg_type: Aggregation type (qa, qm, sdd)
        run_id: Run identifier

    Returns:
        True if run directory exists, False otherwise
    """
    run_dir = output_root / agg_type / run_id
    return run_dir.exists()
