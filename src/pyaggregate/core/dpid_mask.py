# pattern: Functional Core
"""Pure function for masking dp with surrogate_id."""

import polars as pl


def mask_dpid(frame: pl.DataFrame, dpid_map: pl.DataFrame) -> pl.DataFrame:
    """Left-join frame on dp to get surrogate_id, drop original dp.

    Pure function that transforms a DataFrame by replacing the `dp` column
    with `surrogate_id` from a dpid_map lookup table. The lookup table's
    `dpid` column is treated as equivalent to the frame's `dp` column.

    Args:
        frame: Input DataFrame with a `dp` column
        dpid_map: Lookup table with columns `dpid` and `surrogate_id`

    Returns:
        DataFrame with `dp` replaced by `surrogate_id`. Row count preserved.
        Unmapped dps result in null `surrogate_id` values.
    """
    lookup = dpid_map.select(pl.col("dpid").alias("dp"), pl.col("surrogate_id"))
    joined = frame.join(lookup, on="dp", how="left")
    return joined.drop("dp")
