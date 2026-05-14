# pattern: Functional Core
"""Pure functions for input resolution and catalog filtering."""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from pyaggregate.config import AggTypeConfig


@dataclass(frozen=True)
class TableInput:
    """Resolved input for a single table from a single DP."""

    dpid: str
    msoc_path: Path
    reqtype: str


def filter_catalog(catalog: pl.DataFrame, agg_config: AggTypeConfig) -> pl.DataFrame:
    """Filter catalog rows based on aggregation type configuration.

    For qa/qm types: filters to catalog rows where reqtype == source_reqtype
    For sdd type: filters to catalog rows where source_field column == 1

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


def group_inputs_by_table(
    table_listings: list[tuple[str, str, Path, str]],
    agg_config: AggTypeConfig,
) -> dict[str, list[TableInput]]:
    """Group pre-resolved table inputs by table name.

    Takes a list of (table_name, dpid, msoc_path, reqtype) tuples
    (typically from glob operations) and groups them by table name.

    Args:
        table_listings: List of tuples (table_name, dpid, msoc_path, reqtype)
        agg_config: Aggregation config (unused in grouping, for signature consistency)

    Returns:
        Dictionary mapping table_name -> list of TableInput objects
    """
    result: dict[str, list[TableInput]] = {}

    for table_name, dpid, msoc_path, reqtype in table_listings:
        if table_name not in result:
            result[table_name] = []

        result[table_name].append(
            TableInput(
                dpid=dpid,
                msoc_path=msoc_path,
                reqtype=reqtype,
            )
        )

    return result


def detect_sdd_collisions(inputs: dict[str, list[TableInput]]) -> list[str]:
    """Detect filename collisions in SDD inputs (same file from both qar and qmr).

    For each table, checks if the same (dpid, wpid) appears in both qar and qmr
    reqtype. Returns warning messages for each collision.

    Args:
        inputs: Dictionary mapping table_name -> list of TableInput objects

    Returns:
        List of warning message strings for collisions found
    """
    warnings: list[str] = []

    for table_name, inputs_list in inputs.items():
        # Group by dpid
        by_dpid: dict[str, dict[str, list[TableInput]]] = {}

        for table_input in inputs_list:
            dpid = table_input.dpid
            if dpid not in by_dpid:
                by_dpid[dpid] = {}

            reqtype = table_input.reqtype
            if reqtype not in by_dpid[dpid]:
                by_dpid[dpid][reqtype] = []

            by_dpid[dpid][reqtype].append(table_input)

        # Check for collisions: same dpid with both qar and qmr
        for dpid, by_reqtype in by_dpid.items():
            if "qar" in by_reqtype and "qmr" in by_reqtype:
                warnings.append(
                    f"collision detected in {table_name}: same filename from both qar and qmr "
                    f"for dpid={dpid}. both rows will be included in stacked output."
                )

    return warnings
