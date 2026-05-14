# pattern: Imperative Shell
"""CLI entry point for pyaggregate."""

from pathlib import Path

import typer

from pyaggregate.config import load_config, resolve_config_path
from pyaggregate.io.catalog_store import CatalogStore
from pyaggregate.io.scanner import run_scan, run_scan_dry

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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show intended changes without modifying the catalog.",
    ),
) -> None:
    """Walk the requests tree and update the catalog with latest approved submissions."""
    try:
        config_path = resolve_config_path(config)
        cfg = load_config(config_path)

        with CatalogStore(cfg.state.catalog_db) as store:
            if dry_run:
                changes = run_scan_dry(cfg, store)
                if changes:
                    typer.echo("Dry run: intended changes:")
                    for change in changes:
                        typer.echo(f"  {change}")
                else:
                    typer.echo("Dry run: no changes")
            else:
                result = run_scan(cfg, store)
                if result.rows_upserted == 0 and result.errors == 0:
                    # Check if this was a lock contention (info-level log already emitted)
                    typer.echo("Scan complete: no changes")
                else:
                    typer.echo(
                        f"Scan complete: {result.rows_upserted} rows upserted, "
                        f"{result.packages_skipped} packages skipped, "
                        f"{result.errors} errors"
                    )
    except Exception as e:
        typer.echo(f"failed to scan: {e}", err=True)
        raise typer.Exit(code=1) from e


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
