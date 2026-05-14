# pattern: Imperative Shell
"""CLI entry point for pyaggregate."""

from pathlib import Path

import typer

from pyaggregate.config import resolve_config_path

app = typer.Typer(
    name="pyaggregate",
    help="Unified QA, QM, and SCDM Snapshot aggregation CLI.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

CONFIG_OPTION = typer.Option(
    None,
    "--config",
    envvar="PYAGGREGATE_CONFIG",
    help="Path to config file. Can be set via PYAGGREGATE_CONFIG env var.",
)


@app.command()
def scan(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Walk the requests tree and update the catalog with latest approved submissions."""
    _config_path = resolve_config_path(config)
    typer.echo(f"scan: not yet implemented (config: {_config_path})")
    raise typer.Exit(code=1)


@app.command()
def run(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Produce aggregated parquet outputs for QA, QM, and/or SDD."""
    _config_path = resolve_config_path(config)
    typer.echo(f"run: not yet implemented (config: {_config_path})")
    raise typer.Exit(code=1)


@app.command(name="init-db")
def init_db(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Create the sqlite catalog and dpid_map tables."""
    _config_path = resolve_config_path(config)
    typer.echo(f"init-db: not yet implemented (config: {_config_path})")
    raise typer.Exit(code=1)


@app.command(name="show-catalog")
def show_catalog(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Display the current catalog contents."""
    _config_path = resolve_config_path(config)
    typer.echo(f"show-catalog: not yet implemented (config: {_config_path})")
    raise typer.Exit(code=1)


@app.command(name="show-dpid-map")
def show_dpid_map(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Display the DPID surrogate mapping."""
    _config_path = resolve_config_path(config)
    typer.echo(f"show-dpid-map: not yet implemented (config: {_config_path})")
    raise typer.Exit(code=1)


@app.command(name="show-scans")
def show_scans(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Display the scan log history."""
    _config_path = resolve_config_path(config)
    typer.echo(f"show-scans: not yet implemented (config: {_config_path})")
    raise typer.Exit(code=1)
