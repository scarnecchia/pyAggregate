# pattern: Mixed (Orchestration: aggregate_table;
#   Pure: reconcile_schemas, stack_frames, compute_rollup, should_exclude_rollup)
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


# Distribution-statistic column names whose values describe a per-partner
# distribution and therefore cannot be summed across partners. Detected by
# case-insensitive exact name match. Names sourced from the QA data dictionary
# (qa, qa_mil, snapshot) survey of numeric variables.
NEVER_SUM_NAMES: frozenset[str] = frozenset(
    {
        "mean",
        "std",
        "stddev",
        "variance",
        "median",
        "min",
        "max",
        "p1",
        "p5",
        "p10",
        "p25",
        "p50",
        "p75",
        "p90",
        "p95",
        "p99",
    }
)

_TEMPORAL_DTYPES: frozenset[type] = frozenset({pl.Date, pl.Datetime, pl.Time})


def _is_temporal(dtype: pl.DataType) -> bool:
    """True if the dtype is a date/datetime/time column."""
    return type(dtype) in _TEMPORAL_DTYPES


def _is_summable(col: str, dtype: pl.DataType) -> bool:
    """True if a column is a numeric measure safe to sum across partners.

    Excludes:
      - non-numeric columns
      - temporal columns (Date/Datetime/Time)
      - distribution-statistic columns by name (mean, std, percentiles, min/max, etc.)
    """
    if not dtype.is_numeric():
        return False
    if _is_temporal(dtype):
        return False
    return col.lower() not in NEVER_SUM_NAMES


def compute_rollup(
    stacked: pl.DataFrame,
    rollup_keys: list[str] | None,
    rollup_aggs: dict[str, str] | None,
) -> pl.DataFrame:
    """Compute rollup aggregation from stacked DataFrame.

    Rollup collapses rows by grouping on key columns and aggregating numeric measures.
    Removes `dp` and surrogate_id before grouping. Columns that look numeric but
    represent dates or per-partner distribution statistics (mean, std, percentiles,
    min/max) become group keys rather than being summed across partners.

    Args:
        stacked: DataFrame with all stacked rows from multiple DPs
        rollup_keys: Columns to group by. If None, defaults to all columns that
            are not summable measures (i.e., non-numeric, temporal, or
            distribution-statistic columns by name).
        rollup_aggs: Dict mapping column names to aggregation functions.
            If None, "sum" is applied to numeric measure columns only
            (excluding temporal and NEVER_SUM_NAMES columns).

    Returns:
        Aggregated DataFrame with `dp` and surrogate_id removed
    """
    working = stacked.drop(["dp", "surrogate_id"], strict=False)

    summable: dict[str, pl.DataType] = {
        col: dtype
        for col, dtype in working.schema.items()
        if _is_summable(col, dtype)
    }

    if rollup_keys is None:
        rollup_keys_final = [col for col in working.columns if col not in summable]
    else:
        rollup_keys_final = list(rollup_keys)

    if rollup_aggs is None:
        rollup_aggs_final = {
            col: "sum" for col in summable if col not in set(rollup_keys_final)
        }
    else:
        rollup_aggs_final = rollup_aggs

    if rollup_keys_final:
        agg_exprs = [getattr(pl.col(col), agg_fn)() for col, agg_fn in rollup_aggs_final.items()]
        result = working.group_by(rollup_keys_final).agg(agg_exprs)
    else:
        # No keys: aggregate entire DataFrame to single row
        agg_exprs = [getattr(pl.col(col), agg_fn)() for col, agg_fn in rollup_aggs_final.items()]
        result = working.select(agg_exprs)

    return result


def _resolve_target_type(types: set[pl.DataType]) -> pl.DataType:
    """Determine safest common upcast type for a set of conflicting column types."""
    has_float = any(t.is_float() for t in types)
    has_int = any(t.is_integer() for t in types)

    if has_float:
        return pl.Float64()
    if has_int:
        return pl.Int64()
    return pl.Utf8()


def reconcile_schemas(frames: list[pl.LazyFrame]) -> list[pl.LazyFrame]:
    """Detect and resolve type conflicts and structural drift across lazy frames.

    Inspects schemas without collecting. Type conflicts are resolved by upcasting:
    Int→Int64, mixed int/float→Float64, otherwise→Utf8. Structural drift (missing
    columns) is logged as a warning; pl.concat(how="diagonal") handles the null-fill.
    """
    if not frames:
        return frames

    column_types: dict[str, set[pl.DataType]] = {}
    for frame in frames:
        schema = frame.collect_schema()
        for col_name, col_type in schema.items():
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

            target_type = _resolve_target_type(types)

            frames = [
                frame.with_columns(pl.col(col_name).cast(target_type))
                if col_name in frame.collect_schema()
                else frame
                for frame in frames
            ]

    all_columns: set[str] = set()
    for frame in frames:
        all_columns.update(frame.collect_schema().names())

    for frame in frames:
        missing_cols = all_columns - set(frame.collect_schema().names())
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
    """Read, reconcile, and concatenate frames from multiple data partners.

    Schema reconciliation happens on lazy plans (no collection). Only the final
    concat triggers materialisation.
    """
    lazy_frames = [
        reader_fn(ti.msoc_path, table_name, ti.dpid)
        for ti in table_inputs
    ]
    lazy_frames = reconcile_schemas(lazy_frames)
    return pl.concat(lazy_frames, how="diagonal").collect()


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
        empty_stacked = pl.DataFrame({"dp": pl.Series([], dtype=pl.Utf8)})
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
