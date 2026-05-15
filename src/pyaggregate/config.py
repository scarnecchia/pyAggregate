# pattern: Mixed (I/O: load_config, resolve_config_path; Pure: dataclass defs, validation)
"""TOML config loader and dataclass definitions."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType


@dataclass(frozen=True)
class TableOverride:
    """Per-table configuration overrides."""

    rollup_keys: tuple[str, ...] | None = None
    rollup_aggs: dict[str, str] | None = None


@dataclass(frozen=True)
class AggTypeConfig:
    """Configuration for an aggregation type."""

    name: str
    source_reqtype: str | None = None
    source_field: str | None = None
    subdirectory: str | None = None
    exclude_from_rollup: tuple[str, ...] = ()
    table_overrides: MappingProxyType[str, TableOverride] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True)
class ScanConfig:
    """Scan configuration."""

    requests_root: Path


@dataclass(frozen=True)
class StateConfig:
    """State configuration."""

    catalog_db: Path
    log_dir: Path


@dataclass(frozen=True)
class OutputConfig:
    """Output configuration."""

    output_root: Path


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration."""

    scan: ScanConfig
    state: StateConfig
    output: OutputConfig
    agg_types: dict[str, AggTypeConfig]


def load_config(path: Path) -> AppConfig:
    """Load and parse TOML configuration file.

    Args:
        path: Path to TOML config file

    Returns:
        Parsed and validated AppConfig

    Raises:
        ValueError: If required fields are missing or invalid
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Validate and extract [scan]
    if "scan" not in data:
        raise ValueError("missing required [scan] section")

    scan_data = data["scan"]
    if "requests_root" not in scan_data:
        raise ValueError("missing required field 'requests_root' in [scan]")

    scan = ScanConfig(requests_root=Path(scan_data["requests_root"]))

    # Validate and extract [state]
    if "state" not in data:
        raise ValueError("missing required [state] section")

    state_data = data["state"]
    if "catalog_db" not in state_data:
        raise ValueError("missing required field 'catalog_db' in [state]")
    if "log_dir" not in state_data:
        raise ValueError("missing required field 'log_dir' in [state]")

    state = StateConfig(
        catalog_db=Path(state_data["catalog_db"]),
        log_dir=Path(state_data["log_dir"]),
    )

    # Validate and extract [output]
    if "output" not in data:
        raise ValueError("missing required [output] section")

    output_data = data["output"]
    if "output_root" not in output_data:
        raise ValueError("missing required field 'output_root' in [output]")

    output = OutputConfig(output_root=Path(output_data["output_root"]))

    # Parse aggregation types from [agg.*]
    agg_types: dict[str, AggTypeConfig] = {}
    agg_data = data.get("agg", {})

    for agg_name, agg_config in agg_data.items():
        # Extract basic agg type config
        source_reqtype = agg_config.get("source_reqtype")
        source_field = agg_config.get("source_field")
        subdirectory = agg_config.get("subdirectory")
        exclude_from_rollup_list = agg_config.get("exclude_from_rollup", [])

        # Convert list to tuple
        exclude_from_rollup = tuple(exclude_from_rollup_list)

        # Parse per-table overrides from [agg.<name>.tables.<table>]
        table_overrides_dict: dict[str, TableOverride] = {}
        tables_data = agg_config.get("tables", {})

        for table_name, table_config in tables_data.items():
            rollup_keys_list = table_config.get("rollup_keys")
            rollup_keys = tuple(rollup_keys_list) if rollup_keys_list else None

            rollup_aggs = table_config.get("rollup_aggs")

            table_override = TableOverride(
                rollup_keys=rollup_keys,
                rollup_aggs=rollup_aggs,
            )
            table_overrides_dict[table_name] = table_override

        # Create immutable mapping for table overrides
        table_overrides = MappingProxyType(table_overrides_dict)

        agg_type = AggTypeConfig(
            name=agg_name,
            source_reqtype=source_reqtype,
            source_field=source_field,
            subdirectory=subdirectory,
            exclude_from_rollup=exclude_from_rollup,
            table_overrides=table_overrides,
        )
        agg_types[agg_name] = agg_type

    return AppConfig(
        scan=scan,
        state=state,
        output=output,
        agg_types=agg_types,
    )


def resolve_config_path(cli_path: Path | None) -> Path:
    """Resolve config file location via precedence chain.

    Precedence (highest to lowest):
    1. CLI --config flag (cli_path parameter)
    2. PYAGGREGATE_CONFIG environment variable
    3. Default ./pyaggregate.toml

    Args:
        cli_path: Config path from CLI flag (if provided)

    Returns:
        Resolved Path to config file
    """
    if cli_path is not None:
        return cli_path

    env_path = os.environ.get("PYAGGREGATE_CONFIG")
    if env_path is not None:
        return Path(env_path)

    return Path("./pyaggregate.toml")
