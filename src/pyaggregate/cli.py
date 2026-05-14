# pattern: Imperative Shell
"""CLI entry point for pyaggregate."""

import logging
from pathlib import Path

import typer

from pyaggregate.config import load_config, resolve_config_path
from pyaggregate.io.catalog_store import CatalogStore
from pyaggregate.io.scanner import run_scan, run_scan_dry
from pyaggregate.log_config import configure_logging

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


def configure_app(verbose: bool = False) -> None:
    """Configure application logging before any subcommand runs.

    This is called as a typer callback before subcommands execute.

    Args:
        verbose: Enable DEBUG level logging
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    configure_logging(log_dir=None, level=log_level)


# Register callback to run before any command
@app.callback()
def main(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Enable DEBUG level logging",
    ),
) -> None:
    """pyaggregate: Unified QA, QM, and SCDM Snapshot aggregation."""
    configure_app(verbose)


def classify_exception(exc: Exception) -> str:
    """Classify an exception into structured error categories.

    Maps exceptions to literal error classes that operators can filter on
    without parsing error messages. Helps distinguish source vs parsing issues.

    Args:
        exc: The exception to classify

    Returns:
        One of: "source_missing", "source_permission", "parse_error",
        "arrow_error", or "unknown"
    """
    if isinstance(exc, FileNotFoundError):
        return "source_missing"
    if isinstance(exc, PermissionError):
        return "source_permission"
    if exc.__class__.__module__.startswith("pyarrow"):
        return "arrow_error"
    if isinstance(exc, (ValueError, TypeError)):
        return "parse_error"
    return "unknown"


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

        configure_logging(log_dir=cfg.state.log_dir)

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
    type: list[str] = typer.Option(None, "--type", help="Aggregation type(s) to run"),
    catalog: Path | None = typer.Option(None, help="Path to alternate catalog db"),
    output_root: Path | None = typer.Option(
        None,
        help="Path to alternate output root",
    ),
    run_id: str | None = typer.Option(None, help="Custom run ID (default: today's date)"),
    update_latest: bool = typer.Option(
        True,
        help="Update the latest symlink after successful run",
    ),
    force: bool = typer.Option(False, help="Overwrite existing run directory"),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Produce aggregated parquet outputs for QA, QM, and/or SDD."""
    try:
        from datetime import date

        from pyaggregate.core.pipeline import aggregate_table
        from pyaggregate.io.input_resolver import resolve_inputs
        from pyaggregate.io.sas_reader import read_table
        from pyaggregate.io.writer import check_run_exists, write_run

        # Load config and resolve paths
        config_path = resolve_config_path(config)
        cfg = load_config(config_path)

        configure_logging(log_dir=cfg.state.log_dir)

        # Resolve catalog and output paths
        catalog_db = catalog if catalog is not None else cfg.state.catalog_db
        output_root_path = output_root if output_root is not None else cfg.output.output_root

        # Default run_id to today's date
        if run_id is None:
            run_id = date.today().isoformat()

        # Determine which agg_types to run
        agg_types_to_run = type if type else list(cfg.agg_types.keys())

        # Track if any agg_type had partial failure
        has_any_partial_failure = False

        for agg_type in agg_types_to_run:
            if agg_type not in cfg.agg_types:
                typer.echo(
                    f"failed to run {agg_type}: aggregation type not configured",
                    err=True,
                )
                raise typer.Exit(code=1)

            agg_config = cfg.agg_types[agg_type]

            # Check if run directory exists
            if check_run_exists(output_root_path, agg_type, run_id) and not force:
                typer.echo(
                    f"failed to run {agg_type}: run directory already exists "
                    f"({output_root_path / agg_type / run_id}). Use --force to overwrite.",
                    err=True,
                )
                raise typer.Exit(code=1)

            # Open catalog store and snapshot data
            with CatalogStore(catalog_db) as store:
                catalog_df = store.snapshot_catalog()
                dpid_map_df = store.snapshot_dpid_map()

            # Resolve inputs
            table_inputs_dict = resolve_inputs(catalog_df, agg_config)

            if not table_inputs_dict:
                typer.echo(f"warning: no inputs found for {agg_type}")
                continue

            # Aggregate each table
            table_outputs: dict[str, dict[str, object]] = {}
            tables_skipped: list[dict] = []
            for table_name, table_inputs_list in table_inputs_dict.items():
                try:
                    outputs = aggregate_table(
                        table_inputs=table_inputs_list,
                        dpid_map=dpid_map_df,
                        agg_config=agg_config,
                        table_name=table_name,
                        reader_fn=read_table,
                    )
                    table_outputs[table_name] = outputs
                except Exception as e:
                    error_class = classify_exception(e)
                    typer.echo(
                        f"warning: failed to aggregate table {table_name}: {e}",
                        err=True,
                    )
                    tables_skipped.append(
                        {
                            "table": table_name,
                            "error_class": error_class,
                            "detail": str(e),
                        }
                    )
                    # Continue with remaining tables (partial success)

            # Track exit code for this agg_type
            has_partial_failure = len(tables_skipped) > 0 and len(table_outputs) > 0
            if has_partial_failure:
                has_any_partial_failure = True

            # Write outputs
            if table_outputs:
                write_run(
                    output_root=output_root_path,
                    agg_type=agg_type,
                    run_id=run_id,
                    table_outputs=table_outputs,
                    dpid_map_frame=dpid_map_df,
                    update_latest=update_latest,
                    tables_skipped=tables_skipped,
                )

                typer.echo(
                    f"successfully wrote {len(table_outputs)} tables to "
                    f"{output_root_path / agg_type / run_id}"
                )
                if has_partial_failure:
                    typer.echo(
                        f"warning: {len(tables_skipped)} tables failed to aggregate for {agg_type}",
                        err=True,
                    )
            else:
                if tables_skipped:
                    typer.echo(
                        f"failed to run {agg_type}: all {len(tables_skipped)} "
                        f"tables failed to aggregate",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                else:
                    typer.echo(f"warning: no tables aggregated for {agg_type}", err=True)

        # Exit with code 2 if any agg_type had partial failure
        if has_any_partial_failure:
            raise typer.Exit(code=2)

    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"failed to run: {e}", err=True)
        raise typer.Exit(code=1) from e


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
