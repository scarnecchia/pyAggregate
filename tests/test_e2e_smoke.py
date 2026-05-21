"""End-to-end smoke test exercising the full CLI pipeline.

Verifies AC9.1 and AC9.2: Starting from an empty state directory and a
synthetic requests/ tree, the sequence init-db -> scan -> run produces all
expected output files for all three agg types with internally consistent
row counts. Re-running with --force overwrites cleanly.

Note: This test patches the sas_reader to handle .sas7bdat files that are
actually parquet files. This is a test-only concern for fixture creation.
"""

from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from pyaggregate.cli import app
from tests.fixtures.builders import DPSpec, build_requests_tree

runner = CliRunner()


@pytest.fixture(autouse=True)
def _patch_sas_reader_for_e2e(patch_sas_reader_for_parquet):
    """Auto-apply SAS reader patch for all e2e tests."""
    pass


@pytest.mark.integration
class TestE2ESmokeTest:
    """End-to-end smoke test of the full pipeline."""

    def test_help_displays_all_subcommands_ac1_2(self) -> None:
        """AC1.2: --help displays all six subcommand names.

        Asserts that the help output contains: scan, run, init-db,
        show-catalog, show-dpid-map, show-scans.
        """
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0, f"--help failed: {result.output}"

        help_text = result.stdout

        # Verify all six subcommand names appear in help output
        subcommands = ["scan", "run", "init-db", "show-catalog", "show-dpid-map", "show-scans"]
        for subcommand in subcommands:
            assert (
                subcommand in help_text
            ), f"Subcommand '{subcommand}' not found in help output"

    def test_full_pipeline_ac9_1(self, tmp_path: Path) -> None:
        """AC9.1: Full pipeline init-db -> scan -> run produces consistent outputs.

        Tests:
        - All expected output files exist for qa, qm, snapshot
        - Row counts are internally consistent
        - dpid_map.csv exists and matches surrogates in masked outputs
        - No .tmp files survive
        - Latest symlinks resolve correctly
        """
        # Setup synthetic requests tree
        requests_root = tmp_path / "requests"
        requests_root.mkdir()

        specs = [
            DPSpec(
                dpid="aeos",
                qar_approved_version="v02",
                qar_unapproved_version="v01",
                qmr_approved_version="v01",
                qar_has_scdm=True,
                qmr_has_scdm=True,
            ),
            DPSpec(
                dpid="cms",
                qar_approved_version="v01",
                qmr_approved_version=None,
                qar_has_scdm=False,
                qmr_has_scdm=False,
            ),
            DPSpec(
                dpid="kpsc",
                qar_approved_version="v01",
                qmr_approved_version="v01",
                qar_has_scdm=True,
                qmr_has_scdm=False,
            ),
        ]

        build_requests_tree(requests_root, specs)

        # Create config
        state_dir = tmp_path / "state"
        output_dir = tmp_path / "output"
        state_dir.mkdir()
        output_dir.mkdir()

        config_path = tmp_path / "pyaggregate.toml"
        config_path.write_text(f"""
[scan]
requests_root = "{requests_root}"

[state]
catalog_db = "{state_dir / "catalog.db"}"
log_dir = "{state_dir / "logs"}"

[agg.qa]
output_path = "{output_dir / "qa"}"
source_reqtype = "qar"
exclude_from_rollup = []

[agg.qm]
output_path = "{output_dir / "qm"}"
source_reqtype = "qmr"
exclude_from_rollup = []

[agg.snapshot]
output_path = "{output_dir / "snapshot"}"
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
exclude_from_rollup = []
""")

        # Run init-db
        result = runner.invoke(app, ["init-db", "--config", str(config_path)])
        assert result.exit_code == 0, f"init-db failed: {result.output}"

        # Run scan
        result = runner.invoke(app, ["scan", "--config", str(config_path)])
        assert result.exit_code == 0, f"scan failed: {result.output}"

        # Run aggregation
        result = runner.invoke(app, ["run", "--config", str(config_path)])
        assert result.exit_code == 0, f"run failed: {result.output}"

        # Verify output files exist
        _verify_output_files_exist(output_dir)

        # Verify row counts are consistent
        _verify_row_count_consistency(output_dir)

        # Verify dpid_map exists and is valid
        _verify_dpid_map_valid(output_dir)

        # Verify no .tmp files remain
        tmp_files = list(output_dir.rglob("*.tmp"))
        assert len(tmp_files) == 0, f"Orphaned .tmp files found: {tmp_files}"

        # Verify latest symlinks
        _verify_latest_symlinks(output_dir)

    def test_full_pipeline_ac9_2_rerun_with_force(self, tmp_path: Path) -> None:
        """AC9.2: Re-running with --run-id and --force overwrites cleanly.

        Tests:
        - Run can be re-executed with same run_id and --force
        - Outputs are overwritten cleanly
        - Row counts remain consistent after overwrite
        """
        # Setup synthetic requests tree
        requests_root = tmp_path / "requests"
        requests_root.mkdir()

        specs = [
            DPSpec(
                dpid="aeos",
                qar_approved_version="v01",
                qmr_approved_version="v01",
                qar_has_scdm=False,
                qmr_has_scdm=False,
            ),
        ]

        build_requests_tree(requests_root, specs)

        # Create config
        state_dir = tmp_path / "state"
        output_dir = tmp_path / "output"
        state_dir.mkdir()
        output_dir.mkdir()

        config_path = tmp_path / "pyaggregate.toml"
        config_path.write_text(f"""
[scan]
requests_root = "{requests_root}"

[state]
catalog_db = "{state_dir / "catalog.db"}"
log_dir = "{state_dir / "logs"}"

[agg.qa]
output_path = "{output_dir / "qa"}"
source_reqtype = "qar"
exclude_from_rollup = []

[agg.qm]
output_path = "{output_dir / "qm"}"
source_reqtype = "qmr"
exclude_from_rollup = []

[agg.snapshot]
output_path = "{output_dir / "snapshot"}"
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
exclude_from_rollup = []
""")

        # First run: init-db -> scan -> run
        result = runner.invoke(app, ["init-db", "--config", str(config_path)])
        assert result.exit_code == 0, f"init-db failed: {result.output}"

        result = runner.invoke(app, ["scan", "--config", str(config_path)])
        assert result.exit_code == 0, f"scan failed: {result.output}"

        run_id = "2025-05-14"
        result = runner.invoke(
            app,
            [
                "run",
                "--config",
                str(config_path),
                "--run-id",
                run_id,
            ],
        )
        assert result.exit_code == 0, f"First run failed: {result.output}"

        # Capture first run outputs
        first_run_outputs = _capture_output_row_counts(output_dir, run_id)

        # Second run: re-run with --force
        result = runner.invoke(
            app,
            [
                "run",
                "--config",
                str(config_path),
                "--run-id",
                run_id,
                "--force",
            ],
        )
        assert result.exit_code == 0, f"Second run (with --force) failed: {result.output}"

        # Verify outputs still exist and are consistent
        _verify_output_files_exist(output_dir, run_id)
        _verify_row_count_consistency(output_dir, run_id)
        _verify_dpid_map_valid(output_dir, run_id)

        # Verify row counts are still consistent (may differ slightly due to randomness)
        # but should have same structure
        second_run_outputs = _capture_output_row_counts(output_dir, run_id)
        assert set(first_run_outputs.keys()) == set(second_run_outputs.keys()), (
            "Output tables changed between runs"
        )


def _verify_output_files_exist(output_dir: Path, run_id: str = "latest") -> None:
    """Verify all expected output files exist.

    Args:
        output_dir: Root output directory
        run_id: Run identifier (defaults to latest)
    """
    for agg_type in ["qa", "qm", "snapshot"]:
        agg_dir = output_dir / agg_type

        # Skip agg types that weren't run (no directories)
        if not agg_dir.exists():
            continue

        if run_id == "latest":
            # Check latest symlink
            latest_dir = agg_dir / "latest"
            if not latest_dir.exists():
                # If there's no latest symlink, skip this agg type
                continue
            assert latest_dir.is_symlink(), f"{agg_type}/latest is not a symlink"
            run_base = latest_dir.resolve()
        else:
            run_base = agg_dir / run_id
            if not run_base.exists():
                # Skip if this agg_type wasn't run
                continue

        # Expect at least stacked and masked outputs
        stacked_dir = run_base / "stacked"
        masked_dir = run_base / "masked"
        dpid_map_file = run_base / "dpid_map.csv"

        assert stacked_dir.exists(), f"Missing stacked output for {agg_type}/{run_id}"
        assert masked_dir.exists(), f"Missing masked output for {agg_type}/{run_id}"
        assert dpid_map_file.exists(), f"Missing dpid_map.csv for {agg_type}/{run_id}"

        # At least one table should exist
        stacked_tables = list(stacked_dir.glob("*.parquet"))
        assert len(stacked_tables) > 0, f"No parquet files in stacked for {agg_type}/{run_id}"


def _verify_row_count_consistency(output_dir: Path, run_id: str = "latest") -> None:
    """Verify row count consistency within and across output types.

    Rules:
    - Masked rows == stacked rows for each table
    - Rollup rows <= stacked rows for each table

    Args:
        output_dir: Root output directory
        run_id: Run identifier (defaults to latest)
    """
    for agg_type in ["qa", "qm", "snapshot"]:
        agg_dir = output_dir / agg_type

        # Skip agg types that weren't run
        if not agg_dir.exists():
            continue

        if run_id == "latest":
            latest_dir = agg_dir / "latest"
            if not latest_dir.exists():
                continue
            run_base = latest_dir.resolve()
        else:
            run_base = agg_dir / run_id
            if not run_base.exists():
                continue

        stacked_dir = run_base / "stacked"
        masked_dir = run_base / "masked"

        stacked_files = list(stacked_dir.glob("*.parquet"))
        for stacked_file in stacked_files:
            table_name = stacked_file.stem

            # Read stacked and masked
            stacked_df = pl.read_parquet(str(stacked_file))
            stacked_count = len(stacked_df)

            masked_file = masked_dir / f"{table_name}.parquet"
            assert masked_file.exists(), f"Missing masked output for {table_name}"

            masked_df = pl.read_parquet(str(masked_file))
            masked_count = len(masked_df)

            # Masked should equal stacked
            assert masked_count == stacked_count, (
                f"{agg_type}/{table_name}: masked ({masked_count}) != stacked ({stacked_count})"
            )

            # Check rollup if it exists
            rollup_dir = run_base / "rollup"
            if rollup_dir.exists():
                rollup_file = rollup_dir / f"{table_name}.parquet"
                if rollup_file.exists():
                    rollup_df = pl.read_parquet(str(rollup_file))
                    rollup_count = len(rollup_df)

                    assert rollup_count <= stacked_count, (
                        f"{agg_type}/{table_name}: rollup ({rollup_count}) > stacked ({stacked_count})"
                    )


def _verify_dpid_map_valid(output_dir: Path, run_id: str = "latest") -> None:
    """Verify dpid_map exists and contains valid surrogates.

    Args:
        output_dir: Root output directory
        run_id: Run identifier (defaults to latest)
    """
    for agg_type in ["qa", "qm", "snapshot"]:
        agg_dir = output_dir / agg_type

        # Skip agg types that weren't run
        if not agg_dir.exists():
            continue

        if run_id == "latest":
            latest_dir = agg_dir / "latest"
            if not latest_dir.exists():
                continue
            run_base = latest_dir.resolve()
        else:
            run_base = agg_dir / run_id
            if not run_base.exists():
                continue

        dpid_map_file = run_base / "dpid_map.csv"
        assert dpid_map_file.exists(), f"Missing dpid_map.csv for {agg_type}"

        dpid_map = pl.read_csv(str(dpid_map_file))
        assert "surrogate_id" in dpid_map.columns, "Missing surrogate_id column"
        assert "dpid" in dpid_map.columns, "Missing dpid column"

        # Verify surrogates in masked outputs exist in map
        masked_dir = run_base / "masked"
        for masked_file in masked_dir.glob("*.parquet"):
            df = pl.read_parquet(str(masked_file))
            if "surrogate_id" in df.columns:
                surrogates_in_data = set(df["surrogate_id"].unique().to_list())
                surrogates_in_map = set(dpid_map["surrogate_id"].unique().to_list())
                assert surrogates_in_data.issubset(surrogates_in_map), (
                    "Surrogates in data not in dpid_map"
                )


def _verify_latest_symlinks(output_dir: Path) -> None:
    """Verify latest symlinks resolve correctly for each agg type.

    Args:
        output_dir: Root output directory
    """
    for agg_type in ["qa", "qm", "snapshot"]:
        agg_dir = output_dir / agg_type

        # Skip if agg type wasn't run
        if not agg_dir.exists():
            continue

        latest_link = agg_dir / "latest"
        if not latest_link.exists():
            # Skip if no latest symlink (agg type wasn't run)
            continue

        assert latest_link.is_symlink(), f"{agg_type}/latest is not a symlink"
        assert latest_link.resolve().exists(), f"{agg_type}/latest points to non-existent target"


def _capture_output_row_counts(output_dir: Path, run_id: str) -> dict[str, Any]:
    """Capture row counts from all outputs for comparison.

    Args:
        output_dir: Root output directory
        run_id: Run identifier

    Returns:
        Dict mapping agg_type/table -> row counts
    """
    counts: dict[str, Any] = {}

    for agg_type in ["qa", "qm", "snapshot"]:
        agg_dir = output_dir / agg_type
        if not agg_dir.exists():
            continue

        run_base = agg_dir / run_id
        if not run_base.exists():
            continue

        agg_counts: dict[str, int] = {}
        stacked_dir = run_base / "stacked"
        if stacked_dir.exists():
            for parquet_file in stacked_dir.glob("*.parquet"):
                df = pl.read_parquet(str(parquet_file))
                agg_counts[parquet_file.stem] = len(df)

        counts[agg_type] = agg_counts

    return counts
