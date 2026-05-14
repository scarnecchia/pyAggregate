# pyAggregate: Unify QA, QM, and SDD Aggregation — Implementation Plan

**Goal:** Replace two legacy SAS aggregation programs and an ad-hoc CSV cron script with a single Python CLI (`pyaggregate`) that unifies QA, QM, and SDD aggregation via a shared sqlite catalog.

**Architecture:** Functional-core / imperative-shell split. Pure pipeline logic (mask, rollup, paths) in `core/`, all filesystem and sqlite side effects isolated in `io/`. Parquet outputs in hive-style dated run directories with stable `latest` symlinks for Power BI.

**Tech Stack:** Python 3.11+, polars-runtime-64, polars-readstat, typer, sqlite3 (stdlib), pytest, hypothesis, ruff

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-05-14 — greenfield project, empty directory confirmed. Reference patterns from sibling project `scdm_parquet_tide`.

---

## Acceptance Criteria Coverage

This phase is infrastructure — no acceptance criteria are tested here.

**Verifies:** None (infrastructure phase — verified operationally)

---

## Phase 1: Project scaffolding

**Goal:** Stand up the Python package, dependency manifest, and CLI skeleton on the target Python version.

<!-- START_TASK_1 -->
### Task 1: Create pyproject.toml

**Files:**
- Create: `pyproject.toml`

**Step 1: Create the file**

Create `pyproject.toml` at the project root with the following content. This follows the `scdm_parquet_tide` sibling project layout and the Python programming standards (`src/` layout, `pyproject.toml` only, no `setup.py` or `requirements.txt`).

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "pyaggregate"
version = "0.1.0"
description = "Unified QA, QM, and SCDM Snapshot aggregation CLI"
requires-python = ">=3.11"
dependencies = [
    "polars-runtime-64>=1.40.0",
    "polars-readstat>=0.14.0",
    "typer>=0.12.0",
]

[project.scripts]
pyaggregate = "pyaggregate.cli:app"

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov",
    "hypothesis>=6.100.0",
    "mypy>=1.10.0",
    "ruff>=0.15.12",
    "pre-commit>=4.6.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: tests that hit the filesystem or network"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
target-version = "py311"
line-length = 100
extend-exclude = [
    ".worktrees",
    "build",
    "dist",
]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["E501", "SIM117", "E402", "B904", "SIM105", "SIM401", "B905", "TC001", "F841"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
```

**Step 2: Verify the file is valid TOML**

Run: `python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('OK')"`

Expected: `OK`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create src/ layout and CLI skeleton

**Files:**
- Create: `src/pyaggregate/__init__.py`
- Create: `src/pyaggregate/cli.py`
- Create: `src/pyaggregate/core/__init__.py`
- Create: `src/pyaggregate/io/__init__.py`

**Step 1: Create directory structure and files**

Create `src/pyaggregate/__init__.py`:

```python
"""pyaggregate — unified QA, QM, and SDD aggregation CLI."""
```

Create `src/pyaggregate/core/__init__.py` (empty file).

Create `src/pyaggregate/io/__init__.py` (empty file).

Create `src/pyaggregate/cli.py`:

```python
# pattern: Imperative Shell
"""CLI entry point for pyaggregate."""

import typer

app = typer.Typer(
    name="pyaggregate",
    help="Unified QA, QM, and SCDM Snapshot aggregation CLI.",
    rich_markup_mode="rich",
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
```

**Step 2: Verify directory structure**

Run: `find src -type f | sort`

Expected:
```
src/pyaggregate/__init__.py
src/pyaggregate/cli.py
src/pyaggregate/core/__init__.py
src/pyaggregate/io/__init__.py
```

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Create tests directory and conftest.py

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create the files**

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py`:

```python
"""Shared fixtures for pyaggregate tests."""
```

**Step 2: Verify**

Run: `find tests -type f | sort`

Expected:
```
tests/__init__.py
tests/conftest.py
```

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Create .gitignore

**Files:**
- Create: `.gitignore`

**Step 1: Create the file**

Based on the `scdm_parquet_tide` sibling project, with additions for pyaggregate-specific patterns:

```gitignore
# Compiled Python bytecode
*.py[cod]
__pycache__/

# Python build artifacts
build/
*.egg-info/
.pytest_cache/
.ruff_cache/

# Log files
*.log

# JetBrains IDE
.idea/

# Generated by MacOS
.DS_Store

# Generated by Windows
Thumbs.db

# Local config (user-specific, not committed)
pyaggregate.toml

# Aggregation outputs (produced by pyaggregate run)
outputs/

# sqlite catalog (operational state, not committed)
*.db
*.db-wal
*.db-shm
*.scan.lock

# Worktrees
.worktrees/
```

<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Create .pre-commit-config.yaml

**Files:**
- Create: `.pre-commit-config.yaml`

**Step 1: Create the file**

Following the `scdm_parquet_tide` pattern with ruff hooks. Enable both format and lint hooks from the start since this is a new project with no legacy code:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.12
    hooks:
      - id: ruff-format
      - id: ruff
        args: [--fix]
```

<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Create README.md

**Files:**
- Create: `README.md`

**Step 1: Create the file**

```markdown
# pyaggregate

Unified QA, QM, and SCDM Snapshot aggregation CLI. Replaces the legacy SAS-based QA Aggregation and SCDM Snapshot Aggregation batch programs.

## Install

```bash
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
pre-commit install
```

## Usage

```bash
# Initialize the catalog database
pyaggregate init-db

# Scan for latest approved submissions
pyaggregate scan

# Run all aggregations (qa, qm, sdd)
pyaggregate run

# Run a single aggregation type
pyaggregate run --type qa

# Inspect state
pyaggregate show-catalog
pyaggregate show-dpid-map
pyaggregate show-scans
```

## Operational model

Two cron jobs cover the full lifecycle:

- `*/15 * * * * flock -n /var/run/pyaggregate-scan.lock pyaggregate scan` — scan every 15 minutes
- `0 3 * * 0 pyaggregate run` — aggregate weekly

See `docs/operations.md` for detailed operational documentation.
```

<!-- END_TASK_6 -->

<!-- START_TASK_7 -->
### Task 7: Create example config

**Files:**
- Create: `examples/pyaggregate.toml`

**Step 1: Create the file**

This sample config shows all three aggregation type configurations. It will be referenced by the config loader in Phase 2.

```toml
# pyaggregate configuration
# Copy to ./pyaggregate.toml and adjust paths for your environment.

[scan]
requests_root = "/data/requests"

[state]
catalog_db = "/data/state/catalog.db"
log_dir = "/data/state/logs"

[output]
output_root = "/data/outputs"

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
```

<!-- END_TASK_7 -->

<!-- START_TASK_8 -->
### Task 8: Install, verify, and commit

**Step 1: Install the package in editable mode with dev dependencies**

Run: `pip install -e ".[dev]"`

Expected: Installs without errors. All dependencies resolve.

**Step 2: Verify CLI is reachable**

Run: `pyaggregate --help`

Expected: Exits 0, lists subcommands: `scan`, `run`, `init-db`, `show-catalog`, `show-dpid-map`, `show-scans`.

**Step 3: Verify pytest runs**

Run: `pytest`

Expected: Exits 0 with "no tests ran" or similar (zero tests, zero failures).

**Step 4: Verify ruff passes**

Run: `ruff check src/ tests/`

Expected: No lint errors.

Run: `ruff format --check src/ tests/`

Expected: All files formatted correctly (no changes needed).

**Step 5: Verify mypy passes**

Run: `mypy src/`

Expected: No type errors (success on first run with stubs).

**Step 6: Commit**

```bash
git add pyproject.toml src/ tests/ .gitignore .pre-commit-config.yaml README.md examples/
git commit -m "chore: scaffold pyaggregate package with CLI skeleton and dev tooling"
```

<!-- END_TASK_8 -->
