"""Integration tests for the run orchestration pipeline."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from typer.testing import CliRunner

from pyaggregate.cli import app, classify_exception
from pyaggregate.config import AggTypeConfig, AppConfig, OutputConfig, ScanConfig, StateConfig
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
        output=OutputConfig(output_root=output_root),
        agg_types={
            "qa": AggTypeConfig(name="qa", source_reqtype="qar", exclude_from_rollup=("*_stats",)),
            "qm": AggTypeConfig(name="qm", source_reqtype="qmr", exclude_from_rollup=("*_stats",)),
            "sdd": AggTypeConfig(name="sdd", source_field="has_scdm", subdirectory="scdm_snapshot", exclude_from_rollup=()),
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

[output]
output_root = "{}"

[agg.qa]
source_reqtype = "qar"
exclude_from_rollup = ["*_stats"]

[agg.qm]
source_reqtype = "qmr"
exclude_from_rollup = ["*_stats"]

[agg.sdd]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
exclude_from_rollup = []
""".format(catalog_db, tmp_path / "logs", output_root)
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
        patch("pyaggregate.io.input_resolver.glob_scdm_tables") as mock_glob_sdd_input,
    ):
        mock_read.return_value = pl.DataFrame({"col": [1]})

        def mock_agg_impl(*args, **kwargs):
            table_name = kwargs.get("table_name", "ae")
            return _create_synthetic_table_output(table_name)

        mock_agg.side_effect = mock_agg_impl
        mock_glob_qa_input.return_value = ["ae", "ae_stats"]
        mock_glob_sdd_input.return_value = ["ae", "ae_stats"]
        patches_dict = {
            "read": mock_read,
            "agg": mock_agg,
            "glob_qa": mock_glob_qa_input,
            "glob_sdd": mock_glob_sdd_input,
        }
        yield patches_dict


class TestRunOrchestration:
    """Tests for run command orchestration."""

    def test_run_with_type_filter_qa_sdd_only(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """AC3.7: --type qa --type sdd produces only qa and sdd outputs, no qm directory."""
        config_file, config = test_config

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--type",
                "sdd",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        # Verify qa output exists
        qa_output = config.output.output_root / "qa" / date.today().isoformat()
        assert (qa_output / "stacked").exists()

        # Verify sdd output exists
        sdd_output = config.output.output_root / "sdd" / date.today().isoformat()
        assert (sdd_output / "stacked").exists()

        # Verify qm output does NOT exist
        qm_output = config.output.output_root / "qm"
        assert not (qm_output / date.today().isoformat()).exists()

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
        run_dir = config.output.output_root / "qa" / date.today().isoformat()
        assert run_dir.exists()

        # Verify latest symlink does NOT exist
        latest_link = config.output.output_root / "qa" / "latest"
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
        run_dir = config.output.output_root / "qa" / "2026-05-14-rerun"
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
        assert "already exists" in result2.stdout

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

        run_dir = config.output.output_root / "qa" / "2026-05-14-test"
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
        run_dir = config.output.output_root / "qa" / today
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
        for agg_type in ["qa", "qm", "sdd"]:
            run_dir = config.output.output_root / agg_type / today
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

        latest_link = config.output.output_root / "qa" / "latest"
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

    def test_run_with_alternate_output_root(
        self,
        cli_runner: CliRunner,
        test_config: tuple[Path, AppConfig],
        mock_patches,
    ) -> None:
        """--output-root flag allows alternate output directory."""
        config_file, config = test_config
        alternate_output = config.output.output_root.parent / "alternate_outputs"

        result = cli_runner.invoke(
            app,
            [
                "run",
                "--type",
                "qa",
                "--output-root",
                str(alternate_output),
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

        today = date.today().isoformat()
        run_dir = alternate_output / "qa" / today
        assert run_dir.exists()

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
        summary_path = config.output.output_root / "qa" / today / "run_summary.json"
        assert summary_path.exists()

        with open(summary_path) as f:
            summary = json.load(f)

        assert summary["run_id"] == today
        assert summary["agg_type"] == "qa"
        assert "started_at" in summary
        assert "ended_at" in summary
        assert "tables_succeeded" in summary
        assert "exit_code" in summary


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
