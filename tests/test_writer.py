"""Tests for writer module."""

import json
from pathlib import Path

import polars as pl
import pytest

from pyaggregate.io.writer import check_run_exists, filter_dpid_map, write_run


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
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Check directory structure exists
    assert (output_root / "qa" / "2026-05-14" / "stacked").exists()
    assert (output_root / "qa" / "2026-05-14" / "masked").exists()
    assert (output_root / "qa" / "2026-05-14" / "rollup").exists()


def test_write_run_no_tmp_files_survive(tmp_path, table_outputs, dpid_map):
    """Test AC3.6: After write, no .tmp files exist."""
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Verify no .tmp files exist
    tmp_files = list(output_root.rglob("*.tmp"))
    assert len(tmp_files) == 0, f"Found .tmp files: {tmp_files}"


def test_write_run_parquet_files_created(tmp_path, table_outputs, dpid_map):
    """Test that parquet files are created with correct names."""
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Check parquet files exist
    assert (output_root / "qa" / "2026-05-14" / "stacked" / "ae.parquet").exists()
    assert (output_root / "qa" / "2026-05-14" / "masked" / "ae.parquet").exists()
    assert (output_root / "qa" / "2026-05-14" / "rollup" / "ae.parquet").exists()

    assert (output_root / "qa" / "2026-05-14" / "stacked" / "ae_stats.parquet").exists()
    assert (output_root / "qa" / "2026-05-14" / "masked" / "ae_stats.parquet").exists()


def test_write_run_stats_excluded_no_rollup(tmp_path, table_outputs, dpid_map):
    """Test AC5.3: Stats-excluded table has no rollup dir."""
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # ae_stats should not have rollup file
    assert not (output_root / "qa" / "2026-05-14" / "rollup" / "ae_stats.parquet").exists()


def test_write_run_dpid_map_filtered(tmp_path, table_outputs, dpid_map):
    """Test AC5.3: dpid_map.csv only contains surrogates in masked outputs."""
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # Read dpid_map.csv
    dpid_map_path = output_root / "qa" / "2026-05-14" / "dpid_map.csv"
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
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=True,
    )

    latest_link = output_root / "qa" / "latest"
    assert latest_link.is_symlink()

    # Read where symlink points to
    target = latest_link.readlink()
    assert str(target) == "2026-05-14"

    # Verify it resolves to the run directory
    assert (latest_link / "dpid_map.csv").exists()


def test_write_run_no_symlink_when_update_false(tmp_path, table_outputs, dpid_map):
    """Test AC4.3: update_latest=False skips symlink creation."""
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    latest_link = output_root / "qa" / "latest"
    assert not latest_link.exists()


def test_write_run_atomic_symlink_update(tmp_path, table_outputs, dpid_map):
    """Test AC8.2: Symlink update is atomic—never broken during swap."""
    output_root = tmp_path / "outputs"

    # First run with update_latest=True
    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-13",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=True,
    )

    latest_link = output_root / "qa" / "latest"
    assert latest_link.readlink() == Path("2026-05-13")

    # Second run, update symlink
    write_run(
        output_root=output_root,
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
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    summary_path = output_root / "qa" / "2026-05-14" / "run_summary.json"
    assert summary_path.exists()

    with open(summary_path) as f:
        summary = json.load(f)

    assert summary["run_id"] == "2026-05-14"
    assert summary["agg_type"] == "qa"
    assert "started_at" in summary
    assert "ended_at" in summary
    assert "tables_succeeded" in summary
    assert "tables_skipped" in summary
    assert "exit_code" in summary
    assert summary["exit_code"] == 0


def test_write_run_summary_json_with_skipped_tables(tmp_path, table_outputs, dpid_map):
    """Test that run_summary.json includes tables_skipped from CLI failures."""
    output_root = tmp_path / "outputs"

    tables_skipped = [
        {
            "table": "bad_table",
            "error_class": "parse_error",
            "detail": "ValueError: invalid column",
        }
    ]

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
        tables_skipped=tables_skipped,
    )

    summary_path = output_root / "qa" / "2026-05-14" / "run_summary.json"
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
    output_root = tmp_path / "outputs"

    write_run(
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    assert check_run_exists(output_root, "qa", "2026-05-14") is True


def test_check_run_exists_returns_false(tmp_path):
    """Test that check_run_exists returns False for non-existent run."""
    output_root = tmp_path / "outputs"

    assert check_run_exists(output_root, "qa", "2026-05-14") is False


def test_write_run_cleans_orphaned_tmp_files(tmp_path, table_outputs, dpid_map):
    """Test that orphaned .tmp files from previous runs are cleaned up."""
    output_root = tmp_path / "outputs"
    run_dir = output_root / "qa" / "2026-05-14"

    # Create orphaned tmp file
    run_dir.mkdir(parents=True, exist_ok=True)
    orphaned_tmp = run_dir / "stacked" / "orphaned.tmp"
    orphaned_tmp.parent.mkdir(parents=True, exist_ok=True)
    orphaned_tmp.write_text("orphaned")

    assert orphaned_tmp.exists()

    # Write run
    write_run(
        output_root=output_root,
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
    output_root = tmp_path / "outputs"

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
        output_root=output_root,
        agg_type="qa",
        run_id="2026-05-14",
        table_outputs=table_outputs,
        dpid_map_frame=dpid_map,
        update_latest=False,
    )

    # dpid_map.csv should exist and be empty (schema preserved)
    dpid_map_path = output_root / "qa" / "2026-05-14" / "dpid_map.csv"
    assert dpid_map_path.exists()

    written_map = pl.read_csv(dpid_map_path)
    # Should have the right columns but 0 rows
    assert "surrogate_id" in written_map.columns
    assert len(written_map) == 0


class TestFilterDpidMap:
    """Direct unit tests for filter_dpid_map pure function."""

    def test_filters_to_used_surrogates(self) -> None:
        dpid_map = pl.DataFrame({
            "dpid": ["aeos", "cms", "kpsc"],
            "surrogate_id": ["dp_001", "dp_002", "dp_003"],
            "first_seen_at": ["2026-01-01"] * 3,
        })
        table_outputs = {
            "ae": {
                "masked": pl.DataFrame({"surrogate_id": ["dp_001", "dp_002"], "val": [1, 2]}),
            },
        }

        result = filter_dpid_map(dpid_map, table_outputs)

        assert result.height == 2
        assert set(result["surrogate_id"].to_list()) == {"dp_001", "dp_002"}

    def test_empty_masked_surrogates_returns_zero_rows(self) -> None:
        dpid_map = pl.DataFrame({
            "dpid": ["aeos"],
            "surrogate_id": ["dp_001"],
            "first_seen_at": ["2026-01-01"],
        })
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
        dpid_map = pl.DataFrame({
            "dpid": ["aeos"],
            "surrogate_id": ["dp_001"],
            "first_seen_at": ["2026-01-01"],
        })
        table_outputs = {
            "ae": {
                "masked": pl.DataFrame({
                    "surrogate_id": [None, "dp_001"],
                    "val": [1, 2],
                }),
            },
        }

        result = filter_dpid_map(dpid_map, table_outputs)

        assert result.height == 1
        assert result["surrogate_id"][0] == "dp_001"
