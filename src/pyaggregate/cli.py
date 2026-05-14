# pattern: Imperative Shell
"""CLI entry point for pyaggregate."""

from pathlib import Path

import typer

from pyaggregate.config import load_config, resolve_config_path
from pyaggregate.io.catalog_store import CatalogStore

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
    try:
        config_path = resolve_config_path(config)
        cfg = load_config(config_path)

        with CatalogStore(cfg.state.catalog_db) as store:
            store.init_schema()

        typer.echo(f"Initialized database at {cfg.state.catalog_db}")
    except Exception as e:
        typer.echo(f"failed to initialize database: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command(name="show-catalog")
def show_catalog(
    config: Path | None = CONFIG_OPTION,
    catalog: Path | None = typer.Option(
        None,
        "--catalog",
        help="Alternate catalog database path (overrides config)",
    ),
) -> None:
    """Display the current catalog contents."""
    try:
        config_path = resolve_config_path(config)
        cfg = load_config(config_path)

        # Use alternate catalog if provided, otherwise use configured one
        db_path = catalog if catalog is not None else cfg.state.catalog_db

        with CatalogStore(db_path) as store:
            df = store.snapshot_catalog()

        print(df)
    except Exception as e:
        typer.echo(f"failed to display catalog: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command(name="show-dpid-map")
def show_dpid_map(
    config: Path | None = CONFIG_OPTION,
    catalog: Path | None = typer.Option(
        None,
        "--catalog",
        help="Alternate catalog database path (overrides config)",
    ),
) -> None:
    """Display the DPID surrogate mapping."""
    try:
        config_path = resolve_config_path(config)
        cfg = load_config(config_path)

        # Use alternate catalog if provided, otherwise use configured one
        db_path = catalog if catalog is not None else cfg.state.catalog_db

        with CatalogStore(db_path) as store:
            df = store.snapshot_dpid_map()

        print(df)
    except Exception as e:
        typer.echo(f"failed to display dpid_map: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command(name="show-scans")
def show_scans(
    config: Path | None = CONFIG_OPTION,
    catalog: Path | None = typer.Option(
        None,
        "--catalog",
        help="Alternate catalog database path (overrides config)",
    ),
) -> None:
    """Display the scan log history."""
    try:
        config_path = resolve_config_path(config)
        cfg = load_config(config_path)

        # Use alternate catalog if provided, otherwise use configured one
        db_path = catalog if catalog is not None else cfg.state.catalog_db

        with CatalogStore(db_path) as store:
            df = store.snapshot_scan_log()

        print(df)
    except Exception as e:
        typer.echo(f"failed to display scans: {e}", err=True)
        raise typer.Exit(code=1) from e
