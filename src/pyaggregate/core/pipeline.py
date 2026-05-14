# pattern: Functional Core
"""Pipeline orchestration for stacked and masked aggregation outputs."""

from typing import Callable

import polars as pl

from pyaggregate.config import AggTypeConfig
from pyaggregate.core.dpid_mask import mask_dpid
from pyaggregate.core.input_resolution import TableInput


def aggregate_table(
    table_inputs: list[TableInput],
    dpid_map: pl.DataFrame,
    agg_config: AggTypeConfig,
    table_name: str,
    reader_fn: Callable,
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
    frames: list[pl.DataFrame] = []
    for frame in lazy_frames:
        frames.append(frame.collect())

    # Concatenate with diagonal strategy to handle schema drift
    stacked = pl.concat(frames, how="diagonal")

    # Apply masking
    masked = mask_dpid(stacked, dpid_map)

    return {"stacked": stacked, "masked": masked}
