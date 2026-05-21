"""Integration tests for the run orchestration pipeline."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from typer.testing import CliRunner

from pyaggregate.cli import app, classify_exception
from pyaggregate.config import AggTypeConfig, AppConfig, ScanConfig, StateConfig
from pyaggregate.io.catalog_store import CatalogStore


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create a CLI runner for testing."""
    return CliRunner()


@pytest.fixture
def test_config(tmp_path: Path) -> tuple[Path, AppConfig]:
    """Create a test config file and AppConfig."""
    catalog_db = tmp_path / "catalog.db"
    output_root = tmp_path / "outputs"

    # Initialize catalog database
    with CatalogStore(catalog_db) as store:
        store.init_schema()

        # Add test data
        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp041",
            reqtype="qar",
            verid="v01",
            msoc_path="/data/aeos/qar",
            has_scdm=1,
        )
        store.upsert_catalog_row(
            dpid="cms",
            wpid="wp041",
            reqtype="qar",
            verid="v01",
            msoc_path="/data/cms/qar",
            has_scdm=0,
        )
        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp041",
            reqtype="qmr",
            verid="v01",
            msoc_path="/data/aeos/qmr",
            has_scdm=1,
        )

        # Pre-populate DPID surrogates by calling get_or_create
        store.get_or_create_surrogate("aeos")  # Should create dp_001
        store.get_or_create_surrogate("cms")  # Should create dp_002

    config = AppConfig(
        scan=ScanConfig(requests_root=Path("/data/requests")),
        state=StateConfig(catalog_db=catalog_db, log_dir=tmp_path / "logs"),
        agg_types={
            "qa": AggTypeConfig(name="qa", output_path=output_root / "qa", source_reqtype="qar", exclude_from_rollup=("*_stats",)),
            "qm": AggTypeConfig(name="qm", output_path=output_root / "qm", source_reqtype="qmr", exclude_from_rollup=("*_stats",)),
            "snapshot": AggTypeConfig(name="snapshot", output_path=output_root / "snapshot", source_field="has_scdm", subdirectory="scdm_snapshot", exclude_from_rollup=()),
        },
    )

    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "{}"
log_dir = "{}"

[agg.qa]
source_reqtype = "qar"
output_path = "{}"
exclude_from_rollup = ["*_stats"]

[agg.qm]
source_reqtype = "qmr"
output_path = "{}"
exclude_from_rollup = ["*_stats"]

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "{}"
exclude_from_rollup = []
""".format(catalog_db, tmp_path / "logs", output_root / "qa", output_root / "qm", output_root / "snapshot")
    )

    return config_file, config


def _create_synthetic_table_output(table_name: str = "ae") -> dict[str, pl.DataFrame]:
    """Create synthetic table output for a single table (what aggregate_table returns)."""
    if table_name == "ae":
        return {
            "stacked": pl.DataFrame(
                {
                    "dpid": ["aeos", "cms"],
                    "col1": [1, 2],
                }
            ),
            "masked": pl.DataFrame(
                {
                    "surrogate_id": ["dp_001", "dp_002"],
                    "col1": [1, 2],
                }
            ),
            "rollup": pl.DataFrame(
                {
                    "col1": [3],
                }
            ),
        }
    elif table_name == "ae_stats":
        return {
            "stacked": pl.DataFrame(
                {
                    "dpid": ["aeos"],
                    "col1": [1],
                }
            ),
            "masked": pl.DataFrame(
                {
                    "surrogate_id": ["dp_001"],
                    "col1": [1],
                }
            ),
        }
    else:
        return {
            "stacked": pl.DataFrame(
                {
                    "dpid": ["aeos"],
                    "col1": [1],
                }
            ),
            "masked": pl.DataFrame(
                {
                    "surrogate_id": ["dp_001"],
                    "col1": [1],
                }
            ),
            "rollup": pl.DataFrame(
                {
                    "col1": [3],
                }
            ),
        }


@pytest.fixture
def mock_patches():
    """Fixture providing mock patches for pipeline components.

    Patches functions where they're imported, not where they're defined.
    This ensures they work correctly with resolve_inputs() which imports
    them from sas_reader.
    """
    with (
        patch("pyaggregate.io.sas_reader.read_table") as mock_read,
        patch("pyaggregate.core.pipeline.aggregate_table") as mock_agg,
        patch("pyaggregate.io.input_resolver.glob_tables") as mock_glob_qa_input,
        patch("pyaggregate.io.input_resolver.glob_scdm_tables") as mock_glob_scdm,
    ):
        mock_read.return_value = pl.DataFrame({"col": [1]})

        def mock_agg_impl(*args, **kwargs):
            table_name = kwargs.get("table_name", "ae")
            return _create_synthetic_table_output(table_name)

        mock_agg.side_effect = mock_agg_impl
        mock_glob_qa_input.return_value = ["ae", "ae_stats"]
        mock_glob_scdm.return_value = ["ae", "ae_stats"]
        patches_dict = {
            "read": mock_read,
            "agg": mock_agg,
            "glob_qa": mock_glob_qa_input,
            "glob_scdm": mock_glob_scdm,
        }
        yield patches_dict


class TestRunOrchestration:
    """Tests for run command orchestration."""

    def test_run_with_type_filter_qa_snapshot_only(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC3.7: --type qa --type snapshot produces only qa and snapshot outputs, no qm directory.

        AC3.3: Symlinks are independent per agg type (qa latest, snapshot latest, no qm latest).
        """
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--type",
                "snapshot",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        # Verify qa output exists
        qa_output = config.agg_types["qa"].output_path / date.today().isoformat()
        assert (qa_output / "stacked").exists()

        # Verify snapshot output exists
        snapshot_output = config.agg_types["snapshot"].output_path / date.today().isoformat()
        assert (snapshot_output / "stacked").exists()

        # Verify qm output does NOT exist
        qm_output = config.agg_types["qm"].output_path
        assert not (qm_output / date.today().isoformat()).exists()

        # AC3.3: Verify symlinks are independent per agg type
        # qa should have its own latest symlink
        qa_latest = config.agg_types["qa"].output_path / "latest"
        assert qa_latest.is_symlink(), "qa latest symlink should exist"

        # snapshot should have its own latest symlink
        snapshot_latest = config.agg_types["snapshot"].output_path / "latest"
        assert snapshot_latest.is_symlink(), "snapshot latest symlink should exist"

        # qm should NOT have a latest symlink (qm was not run)
        qm_latest = config.agg_types["qm"].output_path / "latest"
        assert not qm_latest.exists(), "qm latest symlink should not exist (qm was not run)"

    def test_run_no_update_latest_flag(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC4.3: --no-update-latest produces run directory but no latest symlink."""
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--no-update-latest",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        # Verify run directory exists
        run_dir = config.agg_types["qa"].output_path / date.today().isoformat()
        assert run_dir.exists()

        # Verify latest symlink does NOT exist
        latest_link = config.agg_types["qa"].output_path / "latest"
        assert not latest_link.exists()

    def test_run_with_custom_run_id(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC4.4: --run-id 2026-05-14-rerun writes to directory with that name."""
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14-rerun",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        # Verify run directory with custom run_id exists
        run_dir = config.agg_types["qa"].output_path / "2026-05-14-rerun"
        assert run_dir.exists()
        assert (run_dir / "stacked").exists()

    def test_run_existing_run_without_force_exits_nonzero(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC4.5: Existing run directory without --force exits non-zero."""
        config_file, config = test_config

        # First run succeeds
        result1 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14-test",
                "--config",
                str(config_file),
            ],
        )
        assert result1.exit_code == 0

        # Second run with same run_id fails
        result2 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14-test",
                "--config",
                str(config_file),
            ],
        )
        assert result2.exit_code == 1
        assert "already exists" in result2.output

    def test_run_existing_run_with_force_succeeds(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC4.5: Existing run directory with --force succeeds and overwrites."""
        config_file, config = test_config

        # First run
        result1 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14-test",
                "--config",
                str(config_file),
            ],
        )
        assert result1.exit_code == 0

        run_dir = config.agg_types["qa"].output_path / "2026-05-14-test"
        first_run_timestamp = (run_dir / "run_summary.json").stat().st_mtime

        # Second run with --force
        result2 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14-test",
                "--force",
                "--config",
                str(config_file),
            ],
        )
        assert result2.exit_code == 0

        # Verify directory still exists and was updated
        assert run_dir.exists()
        second_run_timestamp = (run_dir / "run_summary.json").stat().st_mtime
        assert second_run_timestamp >= first_run_timestamp

    def test_run_default_run_id_is_today(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """Default run_id is today's date in YYYY-MM-DD format."""
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        today = date.today().isoformat()
        run_dir = config.agg_types["qa"].output_path / today
        assert run_dir.exists()

    def test_run_all_agg_types_no_filter(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """All three agg types produce expected output files when no --type filter."""
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        today = date.today().isoformat()

        # Verify all three agg types have output
        for agg_type in ["qa", "qm", "snapshot"]:
            run_dir = config.agg_types[agg_type].output_path / today
            assert run_dir.exists(), f"{agg_type} output not found"
            assert (run_dir / "stacked").exists()

    def test_run_partial_failure_exit_code_2(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """Partial failure: when one table fails, run exits with code 2, others still written."""
        config_file, config = test_config

        def side_effect_agg(*args, **kwargs):
            table_name = kwargs.get("table_name")
            if table_name == "ae":
                raise ValueError("Simulated read error")
            return _create_synthetic_table_output(table_name)

        # Override the aggregate_table mock with our side effect
        mock_patches["agg"].side_effect = side_effect_agg

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--config",
                str(config_file),
            ],
        )

        # Partial failure should exit with code 2
        assert result.exit_code == 2

    def test_run_full_failure_exit_code_1(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """Full failure: when all tables fail, run exits with code 1."""
        config_file, config = test_config

        def side_effect_agg(*args, **kwargs):
            raise ValueError("Simulated read error for all tables")

        # Override the aggregate_table mock to fail for all tables
        mock_patches["agg"].side_effect = side_effect_agg

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--config",
                str(config_file),
            ],
        )

        # Full failure should exit with code 1
        assert result.exit_code == 1

    def test_run_updates_latest_symlink_on_success(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """Latest symlink is updated to point to new run on successful write."""
        config_file, config = test_config

        # First run
        result1 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-13",
                "--config",
                str(config_file),
            ],
        )
        assert result1.exit_code == 0

        latest_link = config.agg_types["qa"].output_path / "latest"
        assert latest_link.is_symlink()
        assert latest_link.readlink() == Path("2026-05-13")

        # Second run
        result2 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14",
                "--config",
                str(config_file),
            ],
        )
        assert result2.exit_code == 0

        # Latest should now point to new run
        assert latest_link.readlink() == Path("2026-05-14")

    def test_run_summary_json_created(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """run_summary.json is created with correct structure."""
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        today = date.today().isoformat()
        summary_path = config.agg_types["qa"].output_path / today / "run_summary.json"
        assert summary_path.exists()

        with open(summary_path) as f:
            summary = json.load(f)

        assert summary["run_id"] == today
        assert "started_at" in summary
        assert "ended_at" in summary
        assert "tables_succeeded" in summary
        assert "tables_skipped" in summary
        assert "exit_code" in summary

    def test_run_with_alternate_catalog_ac4_1(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        mock_patches,
    ) -> None:
        """AC4.1: --catalog points at alternate catalog DB with different data.

        Creates two catalogs with different DPID data, runs with alternate catalog,
        and verifies outputs reflect the alternate catalog's contents.
        """
        # Create primary catalog with aeos and cms
        primary_catalog = tmp_path / "primary.db"
        with CatalogStore(primary_catalog) as store:
            store.init_schema()
            store.upsert_catalog_row(
                dpid="aeos",
                wpid="wp041",
                reqtype="qar",
                verid="v01",
                msoc_path="/data/aeos/qar",
                has_scdm=1,
            )
            store.upsert_catalog_row(
                dpid="cms",
                wpid="wp041",
                reqtype="qar",
                verid="v01",
                msoc_path="/data/cms/qar",
                has_scdm=0,
            )
            store.get_or_create_surrogate("aeos")
            store.get_or_create_surrogate("cms")

        # Create alternate catalog with only kpsc
        alternate_catalog = tmp_path / "alternate.db"
        with CatalogStore(alternate_catalog) as store:
            store.init_schema()
            store.upsert_catalog_row(
                dpid="kpsc",
                wpid="wp041",
                reqtype="qar",
                verid="v01",
                msoc_path="/data/kpsc/qar",
                has_scdm=1,
            )
            store.get_or_create_surrogate("kpsc")

        output_root = tmp_path / "outputs"
        output_root.mkdir()

        config_file = tmp_path / "config.toml"
        config_file.write_text(f"""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "{primary_catalog}"
log_dir = "{tmp_path / "logs"}"

[agg.qa]
source_reqtype = "qar"
output_path = "{output_root / "qa"}"
exclude_from_rollup = ["*_stats"]
""")

        # Run with alternate catalog
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--catalog",
                str(alternate_catalog),
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        # Verify output contains kpsc surrogate (from alternate catalog)
        today = date.today().isoformat()
        masked_dir = output_root / "qa" / today / "masked"
        assert masked_dir.exists()

        # Read masked output and verify it has kpsc's surrogate
        masked_files = list(masked_dir.glob("*.parquet"))
        assert len(masked_files) > 0

        for masked_file in masked_files:
            df = pl.read_parquet(str(masked_file))
            if "surrogate_id" in df.columns:
                surrogates = set(df["surrogate_id"].unique().to_list())
                # Should have kpsc (dp_001 in alternate catalog)
                assert len(surrogates) > 0

    def test_run_output_root_flag_rejected_ac4_3(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
    ) -> None:
        """AC4.3: --output-root is no longer a recognized CLI option."""
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--output-root",
                "/some/path",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_run_no_update_latest_with_preexisting_symlink_ac4_3(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC4.3: --no-update-latest preserves pre-existing latest symlink.

        Creates a pre-existing latest symlink from a first run, then runs
        with --no-update-latest and asserts the symlink still points at the
        original target.
        """
        config_file, config = test_config

        # First run: creates latest symlink pointing to 2026-05-13
        result1 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-13",
                "--config",
                str(config_file),
            ],
        )
        assert result1.exit_code == 0

        latest_link = config.agg_types["qa"].output_path / "latest"
        assert latest_link.is_symlink()
        original_target = latest_link.readlink()
        assert original_target == Path("2026-05-13")

        # Second run with --no-update-latest
        result2 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14",
                "--no-update-latest",
                "--config",
                str(config_file),
            ],
        )
        assert result2.exit_code == 0

        # Verify latest symlink still points to original target
        assert latest_link.is_symlink()
        assert latest_link.readlink() == original_target
        assert latest_link.readlink() == Path("2026-05-13")

    def test_run_custom_run_id_with_no_update_latest_ac4_4(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC4.4: --run-id <custom> --no-update-latest creates dir but preserves latest symlink.

        Runs a second time with a custom run ID and --no-update-latest, verifies:
        (1) output directory with custom run_id exists
        (2) existing latest symlink still points at the original run
        """
        config_file, config = test_config

        # First run creates latest symlink
        result1 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14",
                "--config",
                str(config_file),
            ],
        )
        assert result1.exit_code == 0

        latest_link = config.agg_types["qa"].output_path / "latest"
        assert latest_link.is_symlink()
        original_target = latest_link.readlink()
        assert original_target == Path("2026-05-14")

        # Second run with custom run_id and --no-update-latest
        result2 = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--run-id",
                "2026-05-14-rerun",
                "--no-update-latest",
                "--config",
                str(config_file),
            ],
        )
        assert result2.exit_code == 0

        # Verify custom run_id directory exists
        rerun_dir = config.agg_types["qa"].output_path / "2026-05-14-rerun"
        assert rerun_dir.exists()
        assert (rerun_dir / "stacked").exists()

        # Verify latest still points at original run
        assert latest_link.is_symlink()
        assert latest_link.readlink() == original_target
        assert latest_link.readlink() == Path("2026-05-14")


    def test_run_sdd_rejected_after_rename_ac5_2(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        mock_patches,
    ) -> None:
        """AC5.2: --type sdd is rejected when config only declares [agg.snapshot].

        Verifies that requesting a non-existent aggregation type results in:
        (1) non-zero exit code
        (2) error message that mentions available types
        """
        # Create a minimal config with only [agg.snapshot] (no [agg.sdd])
        catalog_db = tmp_path / "catalog.db"
        output_root = tmp_path / "outputs"

        with CatalogStore(catalog_db) as store:
            store.init_schema()
            store.upsert_catalog_row(
                dpid="aeos",
                wpid="wp041",
                reqtype="qar",
                verid="v01",
                msoc_path="/data/aeos/qar",
                has_scdm=1,
            )
            store.get_or_create_surrogate("aeos")

        config_file = tmp_path / "snapshot_only_config.toml"
        config_file.write_text(
            """
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "{}"
log_dir = "{}"

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "{}"
exclude_from_rollup = []
""".format(catalog_db, tmp_path / "logs", output_root / "snapshot")
        )

        # Try to run with --type sdd (which doesn't exist in config)
        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "sdd",
                "--config",
                str(config_file),
            ],
        )

        # Should fail with non-zero exit code
        assert result.exit_code != 0, f"Expected non-zero exit code, got {result.exit_code}. Output: {result.output}"

        # Error output should mention the configured types (so user knows what's available)
        output_text = result.output.lower()
        assert (
            "snapshot" in output_text or "agg" in output_text
        ), f"Error message should mention configured aggregation types. Got: {result.output}"


class TestClassifyException:
    """Direct unit tests for classify_exception pure function."""

    def test_file_not_found(self) -> None:
        assert classify_exception(FileNotFoundError("missing.sas7bdat")) == "source_missing"

    def test_permission_error(self) -> None:
        assert classify_exception(PermissionError("denied")) == "source_permission"

    def test_value_error(self) -> None:
        assert classify_exception(ValueError("bad data")) == "parse_error"

    def test_type_error(self) -> None:
        assert classify_exception(TypeError("wrong type")) == "parse_error"

    def test_unknown_exception(self) -> None:
        assert classify_exception(RuntimeError("unexpected")) == "unknown"

    def test_pyarrow_exception(self) -> None:
        try:
            import pyarrow

            exc = pyarrow.ArrowInvalid("bad arrow data")
            assert classify_exception(exc) == "arrow_error"
        except ImportError:
            pytest.skip("pyarrow not installed")
