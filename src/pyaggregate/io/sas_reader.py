# pattern: Imperative Shell
"""Polars-readstat SAS file reader wrapper."""

from pathlib import Path

import polars as pl
import polars_readstat
from polars_readstat import ScanReadstat


def scan_readstat(
    path: str,
    schema_overrides: dict[str, pl.DataType] | None = None,
    preserve_order: bool = False,
) -> pl.LazyFrame:
    """Thin wrapper around polars_readstat.scan_readstat for test patching.

    Args:
        path: Path to .sas7bdat file
        schema_overrides: Type overrides for specific columns
        preserve_order: Whether to preserve row order from SAS file

    Returns:
        LazyFrame with data from SAS file
    """
    return polars_readstat.scan_readstat(
        path,
        schema_overrides=schema_overrides or {},
        preserve_order=preserve_order,
    )


def read_table(
    msoc_path: Path,
    table_name: str,
    dpid: str,
    schema_overrides: dict[str, pl.DataType] | None = None,
) -> pl.LazyFrame:
    """Lazily read a SAS table, lowercase columns, and inject dpid.

    Constructs the SAS file path as msoc_path/{table_name}.sas7bdat,
    lowercases all column names via name.to_lowercase(), and injects
    a dpid column with the given value.

    Args:
        msoc_path: Path to msoc directory
        table_name: Name of table (without .sas7bdat extension)
        dpid: Data partner ID to inject into dpid column
        schema_overrides: Type overrides for identifier columns (recommended for large numeric IDs)

    Returns:
        LazyFrame with columns lowercased, dpid column injected, ready to collect
    """
    sas_path = msoc_path / f"{table_name}.sas7bdat"

    lazy_frame = scan_readstat(
        str(sas_path),
        schema_overrides=schema_overrides,
        preserve_order=False,
    )

    # Lowercase all column names
    lazy_frame = lazy_frame.select(pl.all().name.to_lowercase())

    # Inject dpid column
    lazy_frame = lazy_frame.with_columns(pl.lit(dpid).alias("dpid"))

    return lazy_frame


def read_metadata(sas_path: Path) -> dict[str, int | str]:
    """Read metadata from SAS file without loading data.

    Uses ScanReadstat for efficient metadata-only reads.

    Args:
        sas_path: Path to .sas7bdat file

    Returns:
        Dictionary of metadata (number_rows, number_variables, table name, etc.)
    """
    reader = ScanReadstat(str(sas_path))
    return reader.metadata


def glob_tables(
    msoc_path: Path,
    exclude_subdirs: tuple[str, ...] = ("scdm_snapshot",),
) -> list[str]:
    """List .sas7bdat table names directly under msoc_path.

    Scans msoc_path for .sas7bdat files (not in subdirectories),
    excludes files under exclude_subdirs, and returns table names
    (stem without extension).

    Args:
        msoc_path: Path to msoc directory
        exclude_subdirs: Subdirectory names to exclude (default: scdm_snapshot)

    Returns:
        List of table names (sorted)
    """
    tables = []
    for sas_file in msoc_path.glob("*.sas7bdat"):
        tables.append(sas_file.stem)

    return sorted(tables)


def glob_scdm_tables(msoc_path: Path) -> list[str]:
    """List .sas7bdat table names under msoc_path/scdm_snapshot/.

    Args:
        msoc_path: Path to msoc directory

    Returns:
        List of table names in scdm_snapshot (sorted)
    """
    scdm_dir = msoc_path / "scdm_snapshot"

    if not scdm_dir.exists():
        return []

    tables = []
    for sas_file in scdm_dir.glob("*.sas7bdat"):
        tables.append(sas_file.stem)

    return sorted(tables)
