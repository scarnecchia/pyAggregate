# pattern: Functional Core
"""Pure functions for input resolution and catalog filtering."""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from pyaggregate.config import AggTypeConfig


def wpid_sort_key(wpid: str) -> int:
    """Extract numeric portion of workplan ID for sorting.

    Converts wp001, wp002, wp010 to 1, 2, 10 for numeric ordering
    (lexicographic would incorrectly order wp10 before wp2).

    Args:
        wpid: workplan ID string (e.g., wp001, wp002, wp010)

    Returns:
        Numeric sort key
    """
    numeric_part = wpid.removeprefix("wp")
    return int(numeric_part)


@dataclass(frozen=True)
class TableInput:
    """Resolved input for a single table from a single DP."""

    dpid: str
    wpid: str
    msoc_path: Path
    reqtype: str


def filter_catalog(catalog: pl.DataFrame, agg_config: AggTypeConfig) -> pl.DataFrame:
    """Filter catalog rows based on aggregation type configuration.

    For qa/qm types: filters to catalog rows where reqtype == source_reqtype
    For snapshot type: filters to catalog rows where source_field column == 1

    Args:
        catalog: Full catalog DataFrame with dpid, reqtype, and source_field columns
        agg_config: Aggregation configuration specifying filtering criteria

    Returns:
        Filtered DataFrame containing only relevant rows
    """
    if agg_config.source_reqtype is not None:
        return catalog.filter(pl.col("reqtype") == agg_config.source_reqtype)

    if agg_config.source_field is not None:
        return catalog.filter(pl.col(agg_config.source_field) == 1)

    return catalog


def select_latest_workplan_per_dp(catalog: pl.DataFrame) -> pl.DataFrame:
    """Narrow catalog to the highest-wpid row per (dpid, reqtype).

    Catalog rows are already deduped per (dpid, wpid, reqtype) at scan time
    (see core.paths.pick_latest_approved), so each input row represents the
    winning verid for its wpid. This function further narrows to one row per
    (dpid, reqtype) by keeping only the row with the numerically-highest wpid.

    Older workplans remain in the historical catalog but are excluded from
    aggregation runs.

    Args:
        catalog: DataFrame with at least 'dpid', 'wpid', and 'reqtype' columns

    Returns:
        DataFrame with one row per (dpid, reqtype) pair, preserving all columns
    """
    if len(catalog) == 0:
        return catalog

    return (
        catalog.with_columns(
            pl.col("wpid")
            .map_elements(wpid_sort_key, return_dtype=pl.Int64)
            .alias("_wpid_sort_key")
        )
        .sort("_wpid_sort_key", descending=True)
        .group_by(["dpid", "reqtype"], maintain_order=True)
        .first()
        .drop("_wpid_sort_key")
    )


def group_inputs_by_table(
    table_listings: list[tuple[str, str, str, Path, str]],
) -> dict[str, list[TableInput]]:
    """Group pre-resolved table inputs by table name.

    Takes a list of (table_name, dpid, wpid, msoc_path, reqtype) tuples
    (typically from glob operations) and groups them by table name.

    Args:
        table_listings: List of tuples (table_name, dpid, wpid, msoc_path, reqtype)

    Returns:
        Dictionary mapping table_name -> list of TableInput objects
    """
    result: dict[str, list[TableInput]] = {}

    for table_name, dpid, wpid, msoc_path, reqtype in table_listings:
        if table_name not in result:
            result[table_name] = []

        result[table_name].append(
            TableInput(
                dpid=dpid,
                wpid=wpid,
                msoc_path=msoc_path,
                reqtype=reqtype,
            )
        )

    return result


def detect_snapshot_collisions(inputs: dict[str, list[TableInput]]) -> list[str]:
    """Detect filename collisions in snapshot inputs (same file from both qar and qmr).

    For each table, checks if the same (dpid, wpid) appears in both qar and qmr
    reqtype. Returns warning messages for each collision.

    Args:
        inputs: Dictionary mapping table_name -> list of TableInput objects

    Returns:
        List of warning message strings for collisions found
    """
    warnings: list[str] = []

    for table_name, inputs_list in inputs.items():
        # Group by (dpid, wpid)
        by_dpid_wpid: dict[tuple[str, str], dict[str, list[TableInput]]] = {}

        for table_input in inputs_list:
            key = (table_input.dpid, table_input.wpid)
            if key not in by_dpid_wpid:
                by_dpid_wpid[key] = {}

            reqtype = table_input.reqtype
            if reqtype not in by_dpid_wpid[key]:
                by_dpid_wpid[key][reqtype] = []

            by_dpid_wpid[key][reqtype].append(table_input)

        # Check for collisions: same (dpid, wpid) with both qar and qmr
        for (dpid, wpid), by_reqtype in by_dpid_wpid.items():
            if "qar" in by_reqtype and "qmr" in by_reqtype:
                warnings.append(
                    f"collision detected in {table_name}: same filename from both qar and qmr "
                    f"for dpid={dpid}, wpid={wpid}. both rows will be included in stacked output."
                )

    return warnings
