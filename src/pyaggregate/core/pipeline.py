# pattern: Imperative Shell
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
        agg_exprs = [
            getattr(pl.col(col), agg_fn)()
            for col, agg_fn in rollup_aggs_final.items()
        ]
        result = working.group_by(rollup_keys_final).agg(agg_exprs)
    else:
        # No keys: aggregate entire DataFrame to single row
        agg_exprs = [
            getattr(pl.col(col), agg_fn)()
            for col, agg_fn in rollup_aggs_final.items()
        ]
        result = working.select(agg_exprs)

    return result


def aggregate_table(
    table_inputs: list[TableInput],
    dpid_map: pl.DataFrame,
    agg_config: AggTypeConfig,
    table_name: str,
    reader_fn: Callable[[object, str, str], pl.LazyFrame],
) -> dict[str, pl.DataFrame]:
    """Aggregate a table from multiple data providers.

    Orchestrates:
    1. Stack: Read and concatenate LazyFrames from multiple DPs
    2. Mask: Replace dpid with surrogate_id
    3. Rollup: Aggregate by key columns (if not excluded)

    Args:
        table_inputs: List of TableInput objects specifying where to read from
        dpid_map: DataFrame mapping dpid -> surrogate_id
        agg_config: Aggregation configuration for table overrides and exclusions
        table_name: Name of the table being aggregated
        reader_fn: Callable(msoc_path, table_name, dpid) -> LazyFrame

    Returns:
        Dictionary with "stacked", "masked", and "rollup" DataFrames (rollup may be absent)
    """
    # If no inputs, return empty DataFrames with schema
    if not table_inputs:
        empty_stacked = pl.DataFrame({
            "dpid": pl.Series([], dtype=pl.Utf8),
        })
        empty_masked = pl.DataFrame({
            "surrogate_id": pl.Series([], dtype=pl.Int64),
        })
        result = {"stacked": empty_stacked, "masked": empty_masked}
        if not should_exclude_rollup(table_name, agg_config.exclude_from_rollup):
            empty_rollup = pl.DataFrame()
            result["rollup"] = empty_rollup
        return result

    # Read LazyFrames from each DP
    lazy_frames: list[pl.LazyFrame] = []
    for table_input in table_inputs:
        lazy_frame = reader_fn(
            table_input.msoc_path,
            table_name,
            table_input.dpid,
        )
        lazy_frames.append(lazy_frame)

    # Collect frames to DataFrames and check schemas
    frames: list[pl.DataFrame] = [frame.collect() for frame in lazy_frames]

    # Detect and handle schema type conflicts before concatenation
    if frames:
        # Build map of column -> set of types across all frames
        column_types: dict[str, set[pl.DataType]] = {}
        for frame in frames:
            for col_name, col_type in zip(frame.columns, frame.schema.values(), strict=False):
                if col_name not in column_types:
                    column_types[col_name] = set()
                column_types[col_name].add(col_type)

        # Detect type conflicts and apply upcasting
        type_conflicts: dict[str, set[pl.DataType]] = {
            col: types for col, types in column_types.items() if len(types) > 1
        }

        if type_conflicts:
            # Log warning for each type conflict and upcast
            for col_name, types in type_conflicts.items():
                type_names = sorted(str(t) for t in types)
                logger.warning(
                    f"type conflict in column '{col_name}': {type_names}. "
                    f"upcasting to safest common type."
                )

                # Determine safest common type: Int64→Float64, any→Utf8 as last resort
                has_float = any("Float" in str(t) for t in types)
                has_int = any("Int" in str(t) for t in types)

                if has_float:
                    target_type: pl.DataType = pl.Float64()
                elif has_int:
                    target_type = pl.Int64()
                else:
                    target_type = pl.Utf8()

                # Apply cast to all frames
                frames = [
                    frame.with_columns(pl.col(col_name).cast(target_type))
                    if col_name in frame.columns
                    else frame
                    for frame in frames
                ]

        # Detect structural drift (missing/extra columns)
        all_columns = set()
        for frame in frames:
            all_columns.update(frame.columns)

        for frame in frames:
            missing_cols = all_columns - set(frame.columns)
            if missing_cols:
                logger.warning(
                    f"structural drift detected: frame missing columns {sorted(missing_cols)}. "
                    f"they will be filled with nulls."
                )

    # Concatenate with diagonal strategy to handle schema drift
    stacked = pl.concat(frames, how="diagonal")

    # Apply masking
    masked = mask_dpid(stacked, dpid_map)

    # Compute rollup (unless excluded)
    result = {"stacked": stacked, "masked": masked}
    if not should_exclude_rollup(table_name, agg_config.exclude_from_rollup):
        # Look up table-specific overrides from config
        rollup_keys = None
        rollup_aggs = None
        if table_name in agg_config.table_overrides:
            override = agg_config.table_overrides[table_name]
            rollup_keys = list(override.rollup_keys) if override.rollup_keys else None
            rollup_aggs = override.rollup_aggs

        rollup = compute_rollup(stacked, rollup_keys, rollup_aggs)
        result["rollup"] = rollup

    return result
