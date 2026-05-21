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
    output_path: Path,
    agg_type: str,
    run_id: str,
    table_outputs: dict[str, dict[str, pl.DataFrame]],
    dpid_map_frame: pl.DataFrame,
    update_latest: bool,
    tables_skipped: list[dict] | None = None,
) -> None:
    """Write aggregation outputs to disk with atomic temp-rename pattern.

    Writes parquet files to output_path/<run_id>/<output_type>/
    using temp-then-rename for atomicity. Creates dpid_map.csv filtered to
    surrogates actually used in masked outputs. Manages latest symlink atomically.
    Includes aggregation-time failures in run_summary.json.

    Args:
        output_path: Per-agg output directory (from config agg_config.output_path)
        agg_type: Aggregation type label (e.g., "qa", "qm", "snapshot")
        run_id: Run identifier (directory name)
        table_outputs: Dict mapping table_name -> {output_type -> DataFrame}
        dpid_map_frame: Full dpid_map DataFrame to filter
        update_latest: Whether to update the latest symlink
        tables_skipped: List of dicts with {table, error_class, detail} from CLI
    """
    if tables_skipped is None:
        tables_skipped = []

    run_dir = output_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Clean up orphaned .tmp files from previous interrupted runs
    for tmp_file in run_dir.rglob("*.tmp"):
        logger.info("Removing orphaned tmp file: %s", tmp_file)
        tmp_file.unlink()

    started_at = datetime.now(UTC).isoformat()
    tables_succeeded: list[str] = []
    cli_skipped = tables_skipped  # Preserve CLI-provided skipped tables
    tables_skipped_from_writes: list[dict] = []

    # Write parquet files for each table and output type
    for table_name, outputs_dict in table_outputs.items():
        try:
            logger.info(
                "writing output",
                extra={
                    "run_id": run_id,
                    "table": table_name,
                },
            )
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
            logger.error("Failed to write table %s: %s", table_name, e, exc_info=True)
            tables_skipped_from_writes.append(
                {
                    "table": table_name,
                    "error_class": "write_error",
                    "detail": str(e),
                }
            )

    # Combine CLI-provided skipped tables with write errors
    all_skipped = cli_skipped + tables_skipped_from_writes

    # Filter dpid_map using pure function
    filtered_map = filter_dpid_map(dpid_map_frame, table_outputs)

    # Write dpid_map.csv via temp-then-rename
    dpid_map_path = run_dir / "dpid_map.csv"
    dpid_map_tmp = run_dir / "dpid_map.csv.tmp"
    filtered_map.write_csv(str(dpid_map_tmp))
    os.rename(str(dpid_map_tmp), str(dpid_map_path))

    # Write run_summary.json using pure function
    ended_at = datetime.now(UTC).isoformat()
    exit_code = 0 if not all_skipped else 2

    summary = build_run_summary(
        agg_type=agg_type,
        run_id=run_id,
        started_at=started_at,
        ended_at=ended_at,
        tables_succeeded=tables_succeeded,
        tables_skipped=all_skipped,
        exit_code=exit_code,
    )

    summary_path = run_dir / "run_summary.json"
    summary_tmp = run_dir / "run_summary.json.tmp"
    with open(summary_tmp, "w") as f:
        json.dump(summary, f, indent=2)
    os.rename(str(summary_tmp), str(summary_path))

    # Update latest symlink if requested
    if update_latest:
        latest_path = output_path / "latest"
        latest_tmp = output_path / f"latest.{tempfile.gettempprefix()}{os.getpid()}"

        # Create symlink to temp name (relative path to run_id)
        os.symlink(run_id, str(latest_tmp))

        # Atomic rename to final path
        os.rename(str(latest_tmp), str(latest_path))

        logger.info(
            "symlink updated",
            extra={
                "target": run_id,
            },
        )


def filter_dpid_map(
    dpid_map_frame: pl.DataFrame,
    table_outputs: dict[str, dict[str, pl.DataFrame]],
) -> pl.DataFrame:
    """Filter dpid_map to only include surrogates used in this run's masked outputs.

    Extracts and filters to surrogates that appear in the masked outputs of any table in the run.

    Args:
        dpid_map_frame: Full dpid_map DataFrame
        table_outputs: Dict mapping table_name -> {output_type -> DataFrame}

    Returns:
        Filtered DataFrame with only used surrogates, preserving schema even if empty
    """
    masked_surrogates: set[str] = set()
    for _, outputs_dict in table_outputs.items():
        if "masked" in outputs_dict:
            masked_df = outputs_dict["masked"]
            if "surrogate_id" in masked_df.columns:
                surrogates = masked_df.get_column("surrogate_id").unique().to_list()
                masked_surrogates.update(s for s in surrogates if s is not None)

    if masked_surrogates:
        return dpid_map_frame.filter(pl.col("surrogate_id").is_in(list(masked_surrogates)))
    else:
        return dpid_map_frame.head(0)


def build_run_summary(
    agg_type: str,
    run_id: str,
    started_at: str,
    ended_at: str,
    tables_succeeded: list[str],
    tables_skipped: list[dict],
    exit_code: int,
) -> dict:
    """Build the run_summary dict for JSON serialization.

    Constructs the structured summary artifact that operators use to identify failures
    without parsing logs.

    Args:
        agg_type: Aggregation type label (e.g., "qa", "qm", "snapshot")
        run_id: Run identifier
        started_at: ISO timestamp of run start
        ended_at: ISO timestamp of run end
        tables_succeeded: List of table names that succeeded
        tables_skipped: List of dicts with {table, error_class, detail}
        exit_code: Exit code for this run

    Returns:
        Dict ready for JSON serialization
    """
    return {
        "agg_type": agg_type,
        "run_id": run_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "tables_succeeded": tables_succeeded,
        "tables_skipped": tables_skipped,
        "exit_code": exit_code,
    }


def check_run_exists(output_path: Path, run_id: str) -> bool:
    """Check if a run directory already exists.

    Args:
        output_path: Per-agg output directory (from config agg_config.output_path)
        run_id: Run identifier

    Returns:
        True if run directory exists, False otherwise
    """
    run_dir = output_path / run_id
    return run_dir.exists()
