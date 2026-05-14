# pattern: Functional Core
"""Pure function for masking dpid with surrogate_id."""

import polars as pl


def mask_dpid(frame: pl.DataFrame, dpid_map: pl.DataFrame) -> pl.DataFrame:
    """Left-join frame on dpid to get surrogate_id, drop original dpid.

    Pure function that transforms a DataFrame by replacing the `dpid` column
    with `surrogate_id` from a dpid_map lookup table.

    Args:
        frame: Input DataFrame with a `dpid` column
        dpid_map: Lookup table with columns `dpid` and `surrogate_id`

    Returns:
        DataFrame with `dpid` replaced by `surrogate_id`. Row count preserved.
        Unmapped dpids result in null `surrogate_id` values.
    """
    # Left join on dpid column
    joined = frame.join(dpid_map, on="dpid", how="left")

    # Drop the original dpid column
    result = joined.drop("dpid")

    return result
