"""Tests for writer module."""

import json
from pathlib import Path

import polars as pl
import pytest

from pyaggregate.core.input_resolution import TableInput
from pyaggregate.io.writer import (
    build_manifest_entry,
    check_run_exists,
    collect_manifest,
    filter_dpid_map,
    write_run,
)


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


class TestCollectManifest:
    """Tests for collect_manifest function."""

    def test_manifest_version_and_agg_type(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC4.1, AC4.2: manifest_version is 1, agg_type and run_id match."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        assert manifest["manifest_version"] == 1
        assert manifest["agg_type"] == "qa"
        assert manifest["run_id"] == "2026-05-14"

    def test_manifest_tables_sorted_alphabetically(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC5.1: Table names are sorted alphabetically."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        table_names = list(manifest["tables"].keys())
        assert table_names == sorted(table_names)
        assert table_names == ["ae", "ae_stats"]

    def test_manifest_output_types_sorted_alphabetically(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC5.2: Output type keys are sorted alphabetically."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        for _table_name, table_data in manifest["tables"].items():
            output_types = list(table_data["outputs"].keys())
            assert output_types == sorted(output_types)

    def test_manifest_lists_output_types_present(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC2.1: Each table entry lists only the output types that have parquet files."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        # ae should have stacked, masked, rollup
        assert set(manifest["tables"]["ae"]["outputs"].keys()) == {"stacked", "masked", "rollup"}
        # ae_stats should have stacked, masked (no rollup)
        assert set(manifest["tables"]["ae_stats"]["outputs"].keys()) == {"stacked", "masked"}

    def test_manifest_table_without_rollup(self, tmp_path, dpid_map) -> None:
        """Test AC2.5: Table without rollup parquet file has no rollup entry."""
        output_path = tmp_path / "outputs" / "qa"
        # Create table_outputs with no rollup for ae_stats
        table_outputs = {
            "ae": {
                "stacked": pl.DataFrame({"col1": [1]}),
                "masked": pl.DataFrame({"surrogate_id": ["dp_001"], "col1": [1]}),
            },
        }

        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        assert "rollup" not in manifest["tables"]["ae"]["outputs"]

    def test_manifest_dpid_map_num_surrogates(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC3.1: dpid_map.num_surrogates matches filtered dpid_map row count."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        # dpid_map should have been filtered to only dp_001 and dp_002
        assert manifest["dpid_map"]["num_surrogates"] == 2

    def test_manifest_no_masked_outputs_zero_surrogates(self, tmp_path, dpid_map) -> None:
        """Test AC3.2: When no masked outputs exist, num_surrogates is 0."""
        output_path = tmp_path / "outputs" / "qa"
        table_outputs = {
            "ae": {
                "stacked": pl.DataFrame({"col1": [1]}),
            },
        }

        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        assert manifest["dpid_map"]["num_surrogates"] == 0

    def test_manifest_empty_run(self, tmp_path) -> None:
        """Test AC1.4: Empty run (all tables skipped) produces manifest with empty tables object."""
        output_path = tmp_path / "outputs" / "qa"
        run_dir = output_path / "2026-05-14"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Create dpid_map.csv with zero rows
        dpid_df = pl.DataFrame(
            {
                "dpid": [],
                "surrogate_id": [],
                "first_seen_at": [],
            }
        )
        dpid_df.write_csv(str(run_dir / "dpid_map.csv"))

        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        assert manifest["tables"] == {}
        assert manifest["dpid_map"]["num_surrogates"] == 0

    def test_manifest_input_provenance_structure(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC6.1, AC6.2: inputs contains all TableInput fields."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        table_inputs_dict = {
            "ae": [
                TableInput(
                    dpid="aeos",
                    wpid="wp001",
                    msoc_path=Path("/data/msoc/aeos"),
                    reqtype="REQUEST",
                ),
            ],
        }

        manifest = collect_manifest(run_dir, "qa", "2026-05-14", table_inputs_dict)

        assert "ae" in manifest["inputs"]
        assert len(manifest["inputs"]["ae"]) == 1
        input_entry = manifest["inputs"]["ae"][0]
        assert input_entry["dpid"] == "aeos"
        assert input_entry["wpid"] == "wp001"
        assert input_entry["msoc_path"] == "/data/msoc/aeos"
        assert input_entry["reqtype"] == "REQUEST"

    def test_manifest_msoc_path_absolute(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC6.3: msoc_path values are absolute filesystem paths."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        table_inputs_dict = {
            "ae": [
                TableInput(
                    dpid="aeos",
                    wpid="wp001",
                    msoc_path=Path("/absolute/path/to/data"),
                    reqtype="REQUEST",
                ),
            ],
        }

        manifest = collect_manifest(run_dir, "qa", "2026-05-14", table_inputs_dict)

        assert manifest["inputs"]["ae"][0]["msoc_path"].startswith("/")

    def test_manifest_inputs_sorted_by_dpid(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC6.4: Input entries within each table are sorted by dpid."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        table_inputs_dict = {
            "ae": [
                TableInput(
                    dpid="zulu",
                    wpid="wp001",
                    msoc_path=Path("/data/zulu"),
                    reqtype="REQUEST",
                ),
                TableInput(
                    dpid="alpha",
                    wpid="wp001",
                    msoc_path=Path("/data/alpha"),
                    reqtype="REQUEST",
                ),
            ],
        }

        manifest = collect_manifest(run_dir, "qa", "2026-05-14", table_inputs_dict)

        dpids = [entry["dpid"] for entry in manifest["inputs"]["ae"]]
        assert dpids == sorted(dpids)
        assert dpids == ["alpha", "zulu"]

    def test_manifest_table_with_no_inputs(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC6.5: Table not in table_inputs_dict has no entry in inputs."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        table_inputs_dict = {
            "ae": [
                TableInput(
                    dpid="aeos",
                    wpid="wp001",
                    msoc_path=Path("/data/aeos"),
                    reqtype="REQUEST",
                ),
            ],
        }

        manifest = collect_manifest(run_dir, "qa", "2026-05-14", table_inputs_dict)

        # ae_stats is in tables but not in inputs because we didn't provide it
        assert "ae_stats" in manifest["tables"]
        assert "ae_stats" not in manifest["inputs"]

    def test_manifest_default_none_table_inputs_dict(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test that table_inputs_dict defaults to empty dict when None."""
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        # Call with table_inputs_dict=None (default)
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        assert manifest["inputs"] == {}
        # But tables should still be populated from disk
        assert len(manifest["tables"]) > 0

    def test_manifest_corrupt_parquet_tolerance(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test corrupt parquet tolerance: corrupt file skipped, rest succeeds.

        A corrupt parquet file in the run directory is skipped with a warning;
        the rest of the manifest is still correct.
        """
        output_path = tmp_path / "outputs" / "qa"
        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"

        # Create a corrupt parquet file by writing invalid data with .parquet extension
        corrupt_path = run_dir / "stacked" / "corrupt_table.parquet"
        with open(corrupt_path, "w") as f:
            f.write("this is not valid parquet data\n")

        # Call collect_manifest — should skip the corrupt file and succeed
        manifest = collect_manifest(run_dir, "qa", "2026-05-14")

        # Valid parquet files should still be in the manifest
        assert "ae" in manifest["tables"]
        assert "ae_stats" in manifest["tables"]

        # The corrupt_table should not appear in the manifest
        assert "corrupt_table" not in manifest["tables"]

        # Manifest structure should be valid
        assert manifest["manifest_version"] == 1
        assert manifest["agg_type"] == "qa"


class TestManifestIntegration:
    """Tests for manifest.json writing via write_run."""

    def test_manifest_json_created_after_successful_run(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC1.1: Every successful run produces manifest.json in the run directory."""
        output_path = tmp_path / "outputs" / "qa"

        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        manifest_path = output_path / "2026-05-14" / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["manifest_version"] == 1
        assert len(manifest["tables"]) > 0

    def test_manifest_json_created_with_skipped_tables(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC1.2: Partial failure runs (exit 2) also produce manifest.json."""
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

        manifest_path = output_path / "2026-05-14" / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["manifest_version"] == 1

    def test_manifest_json_atomic_write(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test AC1.3: manifest.json is written atomically (no manifest.json.tmp survives)."""
        output_path = tmp_path / "outputs" / "qa"

        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
        )

        run_dir = output_path / "2026-05-14"
        # Verify manifest.json exists
        assert (run_dir / "manifest.json").exists()
        # Verify no manifest.json.tmp survives
        assert not (run_dir / "manifest.json.tmp").exists()

    def test_manifest_json_with_input_provenance(self, tmp_path, table_outputs, dpid_map) -> None:
        """Test that manifest.json includes input provenance when provided."""
        output_path = tmp_path / "outputs" / "qa"

        table_inputs_dict = {
            "ae": [
                TableInput(
                    dpid="aeos",
                    wpid="wp001",
                    msoc_path=Path("/data/msoc/aeos"),
                    reqtype="REQUEST",
                ),
            ],
            "ae_stats": [
                TableInput(
                    dpid="cms",
                    wpid="wp002",
                    msoc_path=Path("/data/msoc/cms"),
                    reqtype="REQUEST",
                ),
            ],
        }

        write_run(
            output_path=output_path,
            agg_type="qa",
            run_id="2026-05-14",
            table_outputs=table_outputs,
            dpid_map_frame=dpid_map,
            update_latest=False,
            table_inputs_dict=table_inputs_dict,
        )

        manifest_path = output_path / "2026-05-14" / "manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert "ae" in manifest["inputs"]
        assert "ae_stats" in manifest["inputs"]
        assert manifest["inputs"]["ae"][0]["dpid"] == "aeos"
        assert manifest["inputs"]["ae_stats"][0]["dpid"] == "cms"
