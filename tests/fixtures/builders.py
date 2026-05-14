# pattern: Functional Core
"""Synthetic SAS fixture builders for end-to-end testing."""

from dataclasses import dataclass
from pathlib import Path

import polars as pl


@dataclass
class DPSpec:
    """Specification for a single data partner in the requests tree."""

    dpid: str
    qar_approved_version: str | None = None
    qar_unapproved_version: str | None = None
    qmr_approved_version: str | None = None
    qar_has_scdm: bool = False
    qmr_has_scdm: bool = False


def build_requests_tree(root: Path, specs: list[DPSpec]) -> None:
    """Build a realistic requests tree with synthetic .sas7bdat files.

    Creates the full requests/{qa,qm}/<dpid>/packages/... directory tree
    and populates it with synthetic .sas7bdat files for testing.

    Args:
        root: Root directory for the requests tree
        specs: List of DPSpec entries defining the structure
    """
    tables = ["ae", "dem"]

    for spec in specs:
        # Create QAR (QA) packages if specified
        if spec.qar_approved_version:
            _create_qar_package(
                root,
                spec.dpid,
                spec.qar_approved_version,
                approved=True,
                has_scdm=spec.qar_has_scdm,
                tables=tables,
            )

        if spec.qar_unapproved_version:
            _create_qar_package(
                root,
                spec.dpid,
                spec.qar_unapproved_version,
                approved=False,
                has_scdm=False,
                tables=tables,
            )

        # Create QMR (QM) packages if specified
        if spec.qmr_approved_version:
            _create_qmr_package(
                root,
                spec.dpid,
                spec.qmr_approved_version,
                approved=True,
                has_scdm=spec.qmr_has_scdm,
                tables=tables,
            )


def _create_qar_package(
    root: Path,
    dpid: str,
    version: str,
    approved: bool,
    has_scdm: bool,
    tables: list[str],
) -> None:
    """Create a QAR package directory with synthetic SAS files.

    Args:
        root: Root of requests tree
        dpid: Data partner ID
        version: Version ID (e.g., "v01", "v02")
        approved: Whether this is an approved package (has msoc) or not (has msoc_new)
        has_scdm: Whether to create scdm_snapshot subdirectory
        tables: List of table names to create
    """
    wpid = "wp041"
    version_dir_name = f"soc_qar_{wpid}_{dpid}_{version}"
    workplan_dir = root / "qa" / dpid / "packages" / f"soc_qar_{wpid}"
    version_dir = workplan_dir / version_dir_name

    version_dir.mkdir(parents=True, exist_ok=True)

    if approved:
        msoc_dir = version_dir / "msoc"
        msoc_dir.mkdir(exist_ok=True)
        _write_synthetic_sas_files(msoc_dir, dpid, tables)

        if has_scdm:
            scdm_dir = msoc_dir / "scdm_snapshot"
            scdm_dir.mkdir(exist_ok=True)
            _write_synthetic_sas_files(scdm_dir, dpid, tables)
    else:
        # Unapproved package: has msoc_new directory instead of msoc
        msoc_new_dir = version_dir / "msoc_new"
        msoc_new_dir.mkdir(exist_ok=True)
        _write_synthetic_sas_files(msoc_new_dir, dpid, tables)


def _create_qmr_package(
    root: Path,
    dpid: str,
    version: str,
    approved: bool,
    has_scdm: bool,
    tables: list[str],
) -> None:
    """Create a QMR package directory with synthetic SAS files.

    Args:
        root: Root of requests tree
        dpid: Data partner ID
        version: Version ID (e.g., "v01", "v02")
        approved: Whether this is an approved package (has msoc) or not (has msoc_new)
        has_scdm: Whether to create scdm_snapshot subdirectory
        tables: List of table names to create
    """
    wpid = "wp042"
    version_dir_name = f"soc_qmr_{wpid}_{dpid}_{version}"
    workplan_dir = root / "qm" / dpid / "packages" / f"soc_qmr_{wpid}"
    version_dir = workplan_dir / version_dir_name

    version_dir.mkdir(parents=True, exist_ok=True)

    if approved:
        msoc_dir = version_dir / "msoc"
        msoc_dir.mkdir(exist_ok=True)
        _write_synthetic_sas_files(msoc_dir, dpid, tables)

        if has_scdm:
            scdm_dir = msoc_dir / "scdm_snapshot"
            scdm_dir.mkdir(exist_ok=True)
            _write_synthetic_sas_files(scdm_dir, dpid, tables)
    else:
        msoc_new_dir = version_dir / "msoc_new"
        msoc_new_dir.mkdir(exist_ok=True)
        _write_synthetic_sas_files(msoc_new_dir, dpid, tables)


def _write_synthetic_sas_files(dir_path: Path, dpid: str, tables: list[str]) -> None:
    """Write synthetic .sas7bdat files for the given tables.

    Creates small parquet files with .sas7bdat extension for testing.
    These will be intercepted by test-mode patching in the e2e test.

    Args:
        dir_path: Directory to write .sas7bdat files to
        dpid: Data partner ID for row identification
        tables: List of table names to create
    """
    for i, table in enumerate(tables):
        # Create synthetic data with consistent schema (uppercase for SAS compatibility)
        data = pl.DataFrame(
            {
                "PATID": [i * 100 + j for j in range(5)],
                "ENR_START": [18262.0] * 5,
                table.upper(): [f"{table}_{j}" for j in range(5)],
            }
        )

        file_path = dir_path / f"{table}.sas7bdat"
        # Write as parquet with .sas7bdat extension - test will patch reader
        data.write_parquet(str(file_path))
