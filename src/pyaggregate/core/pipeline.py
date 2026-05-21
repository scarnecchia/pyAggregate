# pattern: Mixed (Orchestration: aggregate_table; Pure: reconcile_schemas, stack_frames, compute_rollup, should_exclude_rollup)
"""Pipeline orchestration for stacked, masked, and rollup aggregation outputs."""

import fnmatch
import logging
from collections.abc import Callable

import polars as pl

from pyaggregate.config import AggTypeConfig
from pyaggregate.core.dpid_mask import mask_dpid
from pyaggregate.core.input_resolution import TableInput

logger = logging.getLogger(__name__)


def should_exclude_rollup(table_name: str, exclude_patterns: tuple[str, ...]) -> bool:
    """Check if table name matches any exclusion pattern.

    Uses fnmatch for glob-style pattern matching (e.g., "*_stats").

    Args:
        table_name: Name of the table to check
        exclude_patterns: Tuple of fnmatch patterns (e.g., ("*_stats", "lab_*"))

    Returns:
        True if table_name matches any pattern, False otherwise
    """
    return any(fnmatch.fnmatch(table_name, pattern) for pattern in exclude_patterns)


def compute_rollup(
    stacked: pl.DataFrame,
    rollup_keys: list[str] | None,
    rollup_aggs: dict[str, str] | None,
) -> pl.DataFrame:
    """Compute rollup aggregation from stacked DataFrame.

    Rollup collapses rows by grouping on key columns and aggregating numeric columns.
    Removes dpid and surrogate_id before grouping.

    Args:
        stacked: DataFrame with all stacked rows from multiple DPs
        rollup_keys: Columns to group by. If None, all non-numeric columns are used
        rollup_aggs: Dict mapping column names to aggregation functions.
                     If None, "sum" is used for all numeric columns

    Returns:
        Aggregated DataFrame with dpid and surrogate_id removed
    """
    # Drop sensitive identifier columns
    working = stacked.drop(["dpid", "surrogate_id"], strict=False)

    # Determine grouping keys: all non-numeric columns if not specified
    if rollup_keys is None:
        col_types = zip(working.columns, working.schema.values(), strict=True)
        numeric_cols = {col for col, dtype in col_types if dtype.is_numeric()}
        rollup_keys_final = [col for col in working.columns if col not in numeric_cols]
    else:
        rollup_keys_final = list(rollup_keys)

    # Determine aggregations: sum for all numeric columns if not specified
    if rollup_aggs is None:
        col_types = zip(working.columns, working.schema.values(), strict=True)
        numeric_cols = {col for col, dtype in col_types if dtype.is_numeric()}
        # Exclude grouping keys from aggregations
        numeric_cols_to_agg = numeric_cols - set(rollup_keys_final)
        rollup_aggs_final = {col: "sum" for col in numeric_cols_to_agg}
    else:
        rollup_aggs_final = rollup_aggs

    # Apply groupby and aggregation
    if rollup_keys_final:
        agg_exprs = [getattr(pl.col(col), agg_fn)() for col, agg_fn in rollup_aggs_final.items()]
        result = working.group_by(rollup_keys_final).agg(agg_exprs)
    else:
        # No keys: aggregate entire DataFrame to single row
        agg_exprs = [getattr(pl.col(col), agg_fn)() for col, agg_fn in rollup_aggs_final.items()]
        result = working.select(agg_exprs)

    return result


def reconcile_schemas(frames: list[pl.DataFrame]) -> list[pl.DataFrame]:
    """Detect and resolve type conflicts and structural drift across frames.

    Type conflicts are resolved by upcasting: Int→Int64, mixed int/float→Float64,
    otherwise→Utf8. Structural drift (missing columns) is logged as a warning;
    pl.concat(how="diagonal") handles the actual null-fill.
    """
    if not frames:
        return frames

    column_types: dict[str, set[pl.DataType]] = {}
    for frame in frames:
        for col_name, col_type in zip(frame.columns, frame.schema.values(), strict=False):
            if col_name not in column_types:
                column_types[col_name] = set()
            column_types[col_name].add(col_type)

    type_conflicts = {col: types for col, types in column_types.items() if len(types) > 1}

    if type_conflicts:
        for col_name, types in type_conflicts.items():
            type_names = sorted(str(t) for t in types)
            logger.warning(
                f"type conflict in column '{col_name}': {type_names}. "
                f"upcasting to safest common type."
            )

            has_float = any("Float" in str(t) for t in types)
            has_int = any("Int" in str(t) for t in types)

            if has_float:
                target_type: pl.DataType = pl.Float64()
            elif has_int:
                target_type = pl.Int64()
            else:
                target_type = pl.Utf8()

            frames = [
                frame.with_columns(pl.col(col_name).cast(target_type))
                if col_name in frame.columns
                else frame
                for frame in frames
            ]

    all_columns: set[str] = set()
    for frame in frames:
        all_columns.update(frame.columns)

    for frame in frames:
        missing_cols = all_columns - set(frame.columns)
        if missing_cols:
            logger.warning(
                f"structural drift detected: frame missing columns {sorted(missing_cols)}. "
                f"they will be filled with nulls."
            )

    return frames


def stack_frames(
    table_inputs: list[TableInput],
    table_name: str,
    reader_fn: Callable[[object, str, str], pl.LazyFrame],
) -> pl.DataFrame:
    """Read, reconcile, and concatenate frames from multiple data partners."""
    lazy_frames = [
        reader_fn(ti.msoc_path, table_name, ti.dpid)
        for ti in table_inputs
    ]
    frames = [lf.collect() for lf in lazy_frames]
    frames = reconcile_schemas(frames)
    return pl.concat(frames, how="diagonal")


def aggregate_table(
    table_inputs: list[TableInput],
    dpid_map: pl.DataFrame,
    agg_config: AggTypeConfig,
    table_name: str,
    reader_fn: Callable[[object, str, str], pl.LazyFrame],
) -> dict[str, pl.DataFrame]:
    """Aggregate a table from multiple data providers.

    Orchestrates: stack → mask → rollup.
    """
    logger.info(
        "aggregating table",
        extra={
            "table": table_name,
            "agg_type": agg_config.name,
            "input_count": len(table_inputs),
        },
    )

    if not table_inputs:
        empty_stacked = pl.DataFrame({"dpid": pl.Series([], dtype=pl.Utf8)})
        empty_masked = pl.DataFrame({"surrogate_id": pl.Series([], dtype=pl.Utf8)})
        result: dict[str, pl.DataFrame] = {"stacked": empty_stacked, "masked": empty_masked}
        if not should_exclude_rollup(table_name, agg_config.exclude_from_rollup):
            result["rollup"] = pl.DataFrame()
        return result

    stacked = stack_frames(table_inputs, table_name, reader_fn)
    masked = mask_dpid(stacked, dpid_map)

    result = {"stacked": stacked, "masked": masked}
    if not should_exclude_rollup(table_name, agg_config.exclude_from_rollup):
        rollup_keys = None
        rollup_aggs = None
        if table_name in agg_config.table_overrides:
            override = agg_config.table_overrides[table_name]
            rollup_keys = list(override.rollup_keys) if override.rollup_keys else None
            rollup_aggs = override.rollup_aggs
        result["rollup"] = compute_rollup(stacked, rollup_keys, rollup_aggs)

    logger.info(
        "table aggregated",
        extra={
            "table": table_name,
            "stacked_rows": len(stacked),
            "masked_rows": len(masked),
        },
    )

    return result
