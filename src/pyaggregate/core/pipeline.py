# pattern: Imperative Shell
"""Pipeline orchestration for stacked and masked aggregation outputs."""

import logging
from collections.abc import Callable

import polars as pl

from pyaggregate.config import AggTypeConfig
from pyaggregate.core.dpid_mask import mask_dpid
from pyaggregate.core.input_resolution import TableInput

logger = logging.getLogger(__name__)


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

    Args:
        table_inputs: List of TableInput objects specifying where to read from
        dpid_map: DataFrame mapping dpid -> surrogate_id
        agg_config: Aggregation configuration (unused in core logic)
        table_name: Name of the table being aggregated
        reader_fn: Callable(msoc_path, table_name, dpid) -> LazyFrame

    Returns:
        Dictionary with "stacked" and "masked" DataFrames
    """
    # If no inputs, return empty DataFrames with schema
    if not table_inputs:
        empty_stacked = pl.DataFrame({
            "dpid": pl.Series([], dtype=pl.Utf8),
        })
        empty_masked = pl.DataFrame({
            "surrogate_id": pl.Series([], dtype=pl.Int64),
        })
        return {"stacked": empty_stacked, "masked": empty_masked}

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

    return {"stacked": stacked, "masked": masked}
