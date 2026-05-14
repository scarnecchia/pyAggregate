# pattern: Imperative Shell
"""CLI entry point for pyaggregate."""

import typer

app = typer.Typer(
    name="pyaggregate",
    help="Unified QA, QM, and SCDM Snapshot aggregation CLI.",
    no_args_is_help=True,
)


@app.command()
def scan() -> None:
    """Walk the requests tree and update the catalog with latest approved submissions."""
    typer.echo("scan: not yet implemented")
    raise typer.Exit(code=1)


@app.command()
def run() -> None:
    """Produce aggregated parquet outputs for QA, QM, and/or SDD."""
    typer.echo("run: not yet implemented")
    raise typer.Exit(code=1)


@app.command(name="init-db")
def init_db() -> None:
    """Create the sqlite catalog and dpid_map tables."""
    typer.echo("init-db: not yet implemented")
    raise typer.Exit(code=1)


@app.command(name="show-catalog")
def show_catalog() -> None:
    """Display the current catalog contents."""
    typer.echo("show-catalog: not yet implemented")
    raise typer.Exit(code=1)


@app.command(name="show-dpid-map")
def show_dpid_map() -> None:
    """Display the DPID surrogate mapping."""
    typer.echo("show-dpid-map: not yet implemented")
    raise typer.Exit(code=1)


@app.command(name="show-scans")
def show_scans() -> None:
    """Display the scan log history."""
    typer.echo("show-scans: not yet implemented")
    raise typer.Exit(code=1)
