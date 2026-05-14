# pattern: Imperative Shell
"""I/O wrapper for input resolution."""

from pathlib import Path

import polars as pl

from pyaggregate.config import AggTypeConfig
from pyaggregate.core.input_resolution import (
    TableInput,
    filter_catalog,
    group_inputs_by_table,
)
from pyaggregate.io.sas_reader import glob_scdm_tables, glob_tables


def resolve_inputs(
    catalog: pl.DataFrame,
    agg_config: AggTypeConfig,
) -> dict[str, list[TableInput]]:
    """Resolve inputs for aggregation by filtering catalog and globbing filesystem.

    Orchestrates: filter catalog (pure) -> glob filesystems -> group by table (pure).

    For qa/qm: globs msoc_path/*.sas7bdat (excluding subdirectories)
    For sdd: globs msoc_path/{subdirectory}/*.sas7bdat (config-driven, e.g., "scdm_snapshot")

    Args:
        catalog: Full catalog snapshot
        agg_config: Configuration specifying filtering and directory strategy

    Returns:
        Dictionary mapping table_name -> list of TableInput objects
    """
    # Filter catalog to relevant rows
    filtered_catalog = filter_catalog(catalog, agg_config)

    if len(filtered_catalog) == 0:
        return {}

    # Glob filesystem for each catalog row
    table_listings: list[tuple[str, str, str, Path, str]] = []

    for row in filtered_catalog.iter_rows(named=True):
        dpid: str = row["dpid"]
        wpid: str = row["wpid"]
        msoc_path_str: str = row["msoc_path"]
        reqtype: str = row["reqtype"]

        msoc_path = Path(msoc_path_str)

        # Choose glob strategy based on agg_config
        tables = glob_scdm_tables(msoc_path) if agg_config.subdirectory else glob_tables(msoc_path)

        # Add (table_name, dpid, wpid, msoc_path, reqtype) tuples
        for table_name in tables:
            table_listings.append((table_name, dpid, wpid, msoc_path, reqtype))

    # Group by table name
    result = group_inputs_by_table(table_listings)

    return result
