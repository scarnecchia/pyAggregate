"""Tests for writer module."""

import json
from pathlib import Path

import polars as pl
import pytest

from pyaggregate.io.writer import build_manifest_entry, check_run_exists, filter_dpid_map, write_run


@pytest.fixture
def table_outputs() -> dict[str, dict[str, pl.DataFrame]]:
    """Create synthetic table_outputs for testing."""
    return {
        "ae": {
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
        },
        "ae_stats": {
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
            # No "rollup" key — excluded by _stats pattern
        },
    }


@pytest.fixture
def dpid_map() -> pl.DataFrame:
    """Create synthetic dpid_map for testing."""
    return pl.DataFrame(
        {
            "dpid": ["aeos", "cms", "kpsc"],
            "surrogate_id": ["dp_001", "dp_002", "dp_003"],
            "first_seen_at": ["2026-01-01T00:00:00+00:00"] * 3,
        }
    )


def test_write_run_creates_directory_structure(tmp_path, table_outputs, dpid_map):
    """Test that write_run creates correct directory structure."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Check directory structure exists
    assert (output_path / "2026-05-14" / "stacked").exists()
    assert (output_path / "2026-05-14" / "masked").exists()
    assert (output_path / "2026-05-14" / "rollup").exists()


def test_write_run_no_tmp_files_survive(tmp_path, table_outputs, dpid_map):
    """Test AC3.6: After write, no .tmp files exist."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Verify no .tmp files exist
    tmp_files = list(output_path.rglob("*.tmp"))
    assert len(tmp_files) == 0, f"Found .tmp files: {tmp_files}"


def test_write_run_parquet_files_created(tmp_path, table_outputs, dpid_map):
    """Test that parquet files are created with correct names."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Check parquet files exist
    assert (output_path / "2026-05-14" / "stacked" / "ae.parquet").exists()
    assert (output_path / "2026-05-14" / "masked" / "ae.parquet").exists()
    assert (output_path / "2026-05-14" / "rollup" / "ae.parquet").exists()

    assert (output_path / "2026-05-14" / "stacked" / "ae_stats.parquet").exists()
    assert (output_path / "2026-05-14" / "masked" / "ae_stats.parquet").exists()


def test_write_run_stats_excluded_no_rollup(tmp_path, table_outputs, dpid_map):
    """Test AC5.3: Stats-excluded table has no rollup dir."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # ae_stats should not have rollup file
    assert not (output_path / "2026-05-14" / "rollup" / "ae_stats.parquet").exists()


def test_write_run_dpid_map_filtered(tmp_path, table_outputs, dpid_map):
    """Test AC5.3: dpid_map.csv only contains surrogates in masked outputs."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Read dpid_map.csv
    dpid_map_path = output_path / "2026-05-14" / "dpid_map.csv"
    assert dpid_map_path.exists()

    written_map = pl.read_csv(dpid_map_path)

    # Should only contain dp_001 and dp_002 (used in ae and ae_stats masked outputs)
    # Not dp_003 (kpsc, not used)
    surrogates = written_map.get_column("surrogate_id").to_list()
    assert "dp_001" in surrogates
    assert "dp_002" in surrogates
    assert "dp_003" not in surrogates


def test_write_run_latest_symlink_created(tmp_path, table_outputs, dpid_map):
    """Test AC8.1: latest symlink resolves to run_id directory."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=True,
    )

    latest_link = output_path / "latest"
    assert latest_link.is_symlink()

    # Read where symlink points to
    target = latest_link.readlink()
    assert str(target) == "2026-05-14"

    # Verify it resolves to the run directory
    assert (latest_link / "dpid_map.csv").exists()


def test_write_run_no_symlink_when_update_false(tmp_path, table_outputs, dpid_map):
    """Test AC4.3: update_latest=False skips symlink creation."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    latest_link = output_path / "latest"
    assert not latest_link.exists()


def test_write_run_atomic_symlink_update(tmp_path, table_outputs, dpid_map):
    """Test AC8.2: Symlink update is atomic—never broken during swap."""
    output_path = tmp_path / "outputs" / "qa"

    # First run with update_latest=True
    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-13",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=True,
    )

    latest_link = output_path / "latest"
    assert latest_link.readlink() == Path("2026-05-13")

    # Second run, update symlink
    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=True,
    )

    # Verify latest now points to new run
    assert latest_link.readlink() == Path("2026-05-14")

    # Verify it still resolves (never broken)
    assert (latest_link / "dpid_map.csv").exists()


def test_write_run_summary_json(tmp_path, table_outputs, dpid_map):
    """Test that run_summary.json is created with correct structure."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    summary_path = output_path / "2026-05-14" / "run_summary.json"
    assert summary_path.exists()

    with open(summary_path) as f:
        summary = json.load(f)

    assert summary["agg_type"] == "qa"
    assert summary["run_id"] == "2026-05-14"
    assert "started_at" in summary
    assert "ended_at" in summary
    assert "tables_succeeded" in summary
    assert "tables_skipped" in summary
    assert "exit_code" in summary
    assert summary["exit_code"] == 0


def test_write_run_summary_json_with_skipped_tables(tmp_path, table_outputs, dpid_map):
    """Test that run_summary.json includes tables_skipped from CLI failures."""
    output_path = tmp_path / "outputs" / "qa"

    tables_skipped = [
        {
            "table": "bad_table",
            "error_class": "parse_error",
            "detail": "ValueError: invalid column",
        }
    ]

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
        tables_skipped=tables_skipped,
    )

    summary_path = output_path / "2026-05-14" / "run_summary.json"
    assert summary_path.exists()

    with open(summary_path) as f:
        summary = json.load(f)

    # With skipped tables, exit_code should be 2 (partial failure)
    assert summary["exit_code"] == 2
    assert len(summary["tables_skipped"]) == 1
    assert summary["tables_skipped"][0]["table"] == "bad_table"
    assert summary["tables_skipped"][0]["error_class"] == "parse_error"


def test_check_run_exists_returns_true(tmp_path, table_outputs, dpid_map):
    """Test that check_run_exists returns True for existing run."""
    output_path = tmp_path / "outputs" / "qa"

    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    assert check_run_exists(output_path, "2026-05-14") is True


def test_check_run_exists_returns_false(tmp_path):
    """Test that check_run_exists returns False for non-existent run."""
    output_path = tmp_path / "outputs" / "qa"

    assert check_run_exists(output_path, "2026-05-14") is False


def test_write_run_cleans_orphaned_tmp_files(tmp_path, table_outputs, dpid_map):
    """Test that orphaned .tmp files from previous runs are cleaned up."""
    output_path = tmp_path / "outputs" / "qa"
    run_dir = output_path / "2026-05-14"

    # Create orphaned tmp file
    run_dir.mkdir(parents=True, exist_ok=True)
    orphaned_tmp = run_dir / "stacked" / "orphaned.tmp"
    orphaned_tmp.parent.mkdir(parents=True, exist_ok=True)
    orphaned_tmp.write_text("orphaned")

    assert orphaned_tmp.exists()

    # Write run
    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Orphaned tmp should be gone
    assert not orphaned_tmp.exists()

    # But real files should exist
    assert (run_dir / "stacked" / "ae.parquet").exists()


def test_write_run_empty_masked_surrogates(tmp_path, dpid_map):
    """Test edge case: no masked outputs (masked_surrogates is empty).

    Ensures dpid_map.csv can be written even when no surrogates are used.
    This tests the fix for the critical issue where pl.DataFrame(columns=...)
    would crash.
    """
    output_path = tmp_path / "outputs" / "qa"

    # Create table_outputs with empty/no masked dataframes
    table_outputs = {
        "ae": {
            "stacked": pl.DataFrame(
                {
                    "dpid": ["aeos"],
                    "col1": [1],
                }
            ),
            # No masked output, or masked with no surrogate_id column
        }
    }

    # Should not raise an exception
    write_run(
        output_path=output_path,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # dpid_map.csv should exist and be empty (schema preserved)
    dpid_map_path = output_path / "2026-05-14" / "dpid_map.csv"
    assert dpid_map_path.exists()

    written_map = pl.read_csv(dpid_map_path)
    # Should have the right columns but 0 rows
    assert "surrogate_id" in written_map.columns
    assert len(written_map) == 0


class TestFilterDpidMap:
    """Direct unit tests for filter_dpid_map pure function."""

    def test_filters_to_used_surrogates(self) -> None:
        dpid_map = pl.DataFrame(
            {
                "dpid": ["aeos", "cms", "kpsc"],
                "surrogate_id": ["dp_001", "dp_002", "dp_003"],
                "first_seen_at": ["2026-01-01"] * 3,
            }
        )
        table_outputs = {
            "ae": {
                "masked": pl.DataFrame({"surrogate_id": ["dp_001", "dp_002"], "val": [1, 2]}),
            },
        }

        result = filter_dpid_map(dpid_map, table_outputs)

        assert result.height == 2
        assert set(result["surrogate_id"].to_list()) == {"dp_001", "dp_002"}

    def test_empty_masked_surrogates_returns_zero_rows(self) -> None:
        dpid_map = pl.DataFrame(
            {
                "dpid": ["aeos"],
                "surrogate_id": ["dp_001"],
                "first_seen_at": ["2026-01-01"],
            }
        )
        table_outputs = {
            "ae": {
                "stacked": pl.DataFrame({"dpid": ["aeos"], "val": [1]}),
            },
        }

        result = filter_dpid_map(dpid_map, table_outputs)

        assert result.height == 0
        assert "surrogate_id" in result.columns
        assert "dpid" in result.columns

    def test_null_surrogates_excluded(self) -> None:
        dpid_map = pl.DataFrame(
            {
                "dpid": ["aeos"],
                "surrogate_id": ["dp_001"],
                "first_seen_at": ["2026-01-01"],
            }
        )
        table_outputs = {
            "ae": {
                "masked": pl.DataFrame(
                    {
                        "surrogate_id": [None, "dp_001"],
                        "val": [1, 2],
                    }
                ),
            },
        }

        result = filter_dpid_map(dpid_map, table_outputs)

        assert result.height == 1
        assert result["surrogate_id"][0] == "dp_001"


class TestBuildManifestEntry:
    """Tests for build_manifest_entry function."""

    def test_manifest_entry_num_rows(self, tmp_path) -> None:
        """Test AC2.2: num_rows matches parquet content."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        output_dir = run_dir / "stacked"
        output_dir.mkdir()

        df = pl.DataFrame(
            {
                "dpid": ["aeos", "cms", "kpsc"],
                "col1": [1, 2, 3],
            }
        )
        parquet_path = output_dir / "ae.parquet"
        df.write_parquet(str(parquet_path))

        entry = build_manifest_entry(parquet_path, run_dir)

        assert entry["num_rows"] == 3

    def test_manifest_entry_num_columns(self, tmp_path) -> None:
        """Test AC2.3: num_columns matches parquet content."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        output_dir = run_dir / "stacked"
        output_dir.mkdir()

        df = pl.DataFrame(
            {
                "dpid": ["aeos"],
                "col1": [1],
                "col2": [2],
                "col3": [3],
            }
        )
        parquet_path = output_dir / "ae.parquet"
        df.write_parquet(str(parquet_path))

        entry = build_manifest_entry(parquet_path, run_dir)

        assert entry["num_columns"] == 4

    def test_manifest_entry_columns_list(self, tmp_path) -> None:
        """Test AC2.4: columns list contains name and Arrow type for every column."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        output_dir = run_dir / "stacked"
        output_dir.mkdir()

        df = pl.DataFrame(
            {
                "dpid": ["aeos"],
                "count": [42],
            }
        )
        parquet_path = output_dir / "ae.parquet"
        df.write_parquet(str(parquet_path))

        entry = build_manifest_entry(parquet_path, run_dir)

        assert len(entry["columns"]) == 2
        assert entry["columns"][0]["name"] == "dpid"
        assert "string" in entry["columns"][0]["type"].lower()
        assert entry["columns"][1]["name"] == "count"
        assert "int" in entry["columns"][1]["type"].lower()

    def test_manifest_entry_relative_path(self, tmp_path) -> None:
        """Test AC4.3: file value is a relative path."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        output_dir = run_dir / "stacked"
        output_dir.mkdir()

        df = pl.DataFrame({"col1": [1]})
        parquet_path = output_dir / "ae.parquet"
        df.write_parquet(str(parquet_path))

        entry = build_manifest_entry(parquet_path, run_dir)

        assert entry["file"] == "stacked/ae.parquet"
        assert not entry["file"].startswith("/")
