"""Tests for TOML config loader."""

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from pyaggregate.config import (
    AppConfig,
    ScanConfig,
    StateConfig,
    load_config,
    resolve_config_path,
)


class TestLoadConfig:
    """Test TOML config loading."""

    def test_load_valid_config(self, tmp_path: Path) -> None:
        """Load a valid TOML config successfully."""
        config_file = tmp_path / "test_config.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "/data/outputs/qa"
exclude_from_rollup = ["*_stats"]

[agg.qm]
source_reqtype = "qmr"
output_path = "/data/outputs/qm"
exclude_from_rollup = ["*_stats"]

[agg.snapshot]
source_field = "has_scdm"
subdirectory = "scdm_snapshot"
output_path = "/data/outputs/snapshot"
exclude_from_rollup = []
""")

        config = load_config(config_file)

        # Verify top-level structure
        assert isinstance(config, AppConfig)
        assert isinstance(config.scan, ScanConfig)
        assert isinstance(config.state, StateConfig)
        assert isinstance(config.agg_types, dict)

        # Verify scan section
        assert config.scan.requests_root == Path("/data/requests")

        # Verify state section
        assert config.state.catalog_db == Path("/data/state/catalog.db")
        assert config.state.log_dir == Path("/data/state/logs")

        # Verify agg types
        assert "qa" in config.agg_types
        assert "qm" in config.agg_types
        assert "snapshot" in config.agg_types

        # Verify qa config
        qa_config = config.agg_types["qa"]
        assert qa_config.name == "qa"
        assert qa_config.source_reqtype == "qar"
        assert qa_config.output_path == Path("/data/outputs/qa")
        assert qa_config.exclude_from_rollup == ("*_stats",)

        # Verify snapshot config
        snapshot_config = config.agg_types["snapshot"]
        assert snapshot_config.name == "snapshot"
        assert snapshot_config.source_field == "has_scdm"
        assert snapshot_config.subdirectory == "scdm_snapshot"
        assert snapshot_config.output_path == Path("/data/outputs/snapshot")

    def test_missing_scan_section(self, tmp_path: Path) -> None:
        """Raise ValueError when [scan] section is missing."""
        config_file = tmp_path / "bad_config.toml"
        config_file.write_text("""
[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"
""")

        with pytest.raises(ValueError, match="missing.*scan"):
            load_config(config_file)

    def test_missing_requests_root(self, tmp_path: Path) -> None:
        """Raise ValueError when requests_root is missing."""
        config_file = tmp_path / "bad_config.toml"
        config_file.write_text("""
[scan]

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"
""")

        with pytest.raises(ValueError, match="requests_root"):
            load_config(config_file)

    def test_table_override_parsing(self, tmp_path: Path) -> None:
        """Parse per-table overrides in config."""
        config_file = tmp_path / "override_config.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "/data/outputs/qa"

[agg.qa.tables.ae]
rollup_keys = ["col1", "col2"]
rollup_aggs = { "col3" = "sum" }
""")

        config = load_config(config_file)
        qa_config = config.agg_types["qa"]

        # Verify table overrides are present
        assert qa_config.table_overrides is not None
        assert "ae" in qa_config.table_overrides
        ae_override = qa_config.table_overrides["ae"]
        assert ae_override.rollup_keys == ("col1", "col2")
        assert ae_override.rollup_aggs == {"col3": "sum"}

    def test_exclude_from_rollup_defaults_to_empty(self, tmp_path: Path) -> None:
        """Default exclude_from_rollup to empty tuple when not specified."""
        config_file = tmp_path / "default_config.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "/data/outputs/qa"
""")

        config = load_config(config_file)
        qa_config = config.agg_types["qa"]

        # Should default to empty tuple
        assert qa_config.exclude_from_rollup == ()

    def test_dataclass_frozen(self, tmp_path: Path) -> None:
        """Verify all dataclasses are frozen."""
        config_file = tmp_path / "frozen_config.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "/data/outputs/qa"
""")

        config = load_config(config_file)

        # Try to mutate AppConfig
        with pytest.raises(FrozenInstanceError):
            config.scan = ScanConfig(requests_root=Path("/new/path"))  # type: ignore

        # Try to mutate ScanConfig
        with pytest.raises(FrozenInstanceError):
            config.scan.requests_root = Path("/new/path")  # type: ignore

    def test_legacy_output_section_rejected(self, tmp_path: Path) -> None:
        """Reject config with legacy [output] section (AC4.1 and AC4.2)."""
        config_file = tmp_path / "legacy_config.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[output]
output_root = "/data/outputs"

[agg.qa]
source_reqtype = "qar"
output_path = "/data/outputs/qa"
""")

        with pytest.raises(ValueError, match=r"\[output\] section has been removed"):
            load_config(config_file)

    def test_missing_output_path_rejected(self, tmp_path: Path) -> None:
        """Reject config with agg block missing output_path (AC1.4)."""
        config_file = tmp_path / "missing_output_path.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
""")

        with pytest.raises(ValueError, match=r"\[agg\.qa\].*output_path"):
            load_config(config_file)

    def test_output_path_tilde_expansion(self, tmp_path: Path) -> None:
        """Expand ~ in output_path to home directory at load time (AC1.3)."""
        config_file = tmp_path / "tilde_config.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "~/outputs/qa"
""")

        config = load_config(config_file)
        expected_path = Path.home() / "outputs" / "qa"
        assert config.agg_types["qa"].output_path == expected_path

    def test_output_path_relative_preserved(self, tmp_path: Path) -> None:
        """Keep relative output_path relative (AC1.5)."""
        config_file = tmp_path / "relative_config.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = "relative/path"
""")

        config = load_config(config_file)
        assert config.agg_types["qa"].output_path == Path("relative/path")

    def test_output_path_non_string_rejected(self, tmp_path: Path) -> None:
        """Reject non-string output_path values (Minor: type validation)."""
        config_file = tmp_path / "non_string_output_path.toml"
        config_file.write_text("""
[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[agg.qa]
source_reqtype = "qar"
output_path = 42
""")

        with pytest.raises(ValueError, match="output_path must be a string"):
            load_config(config_file)


class TestResolveConfigPath:
    """Test config path resolution."""

    def test_cli_path_takes_precedence(self, tmp_path: Path) -> None:
        """CLI path takes precedence over env var and default."""
        cli_config = tmp_path / "cli_config.toml"
        cli_config.write_text("[scan]\nrequests_root = '/test'")

        env_config = tmp_path / "env_config.toml"
        env_config.write_text("[scan]\nrequests_root = '/test'")

        # Set env var
        old_env = os.environ.get("PYAGGREGATE_CONFIG")
        try:
            os.environ["PYAGGREGATE_CONFIG"] = str(env_config)

            result = resolve_config_path(cli_config)
            assert result == cli_config
        finally:
            if old_env is not None:
                os.environ["PYAGGREGATE_CONFIG"] = old_env
            else:
                os.environ.pop("PYAGGREGATE_CONFIG", None)

    def test_env_var_when_no_cli_path(self, tmp_path: Path) -> None:
        """Env var used when CLI path not provided."""
        env_config = tmp_path / "env_config.toml"
        env_config.write_text("[scan]\nrequests_root = '/test'")

        old_env = os.environ.get("PYAGGREGATE_CONFIG")
        try:
            os.environ["PYAGGREGATE_CONFIG"] = str(env_config)

            result = resolve_config_path(None)
            assert result == env_config
        finally:
            if old_env is not None:
                os.environ["PYAGGREGATE_CONFIG"] = old_env
            else:
                os.environ.pop("PYAGGREGATE_CONFIG", None)

    def test_default_when_no_cli_or_env(self) -> None:
        """Default to ./pyaggregate.toml when no CLI or env."""
        old_env = os.environ.get("PYAGGREGATE_CONFIG")
        try:
            os.environ.pop("PYAGGREGATE_CONFIG", None)

            result = resolve_config_path(None)
            assert result == Path("./pyaggregate.toml")
        finally:
            if old_env is not None:
                os.environ["PYAGGREGATE_CONFIG"] = old_env
