"""Tests for pipeline aggregation orchestration."""

from pathlib import Path

import polars as pl
import pytest

from pyaggregate.config import AggTypeConfig
from pyaggregate.core.input_resolution import TableInput
from pyaggregate.core.pipeline import aggregate_table


def fake_reader(msoc_path: Path, table_name: str, dpid: str) -> pl.LazyFrame:
    """Create synthetic LazyFrame for testing."""
    # Simple test data: return a small frame with the given dpid
    if dpid == "aeos":
        data = pl.DataFrame({
            "patient_id": [1, 2, 3, 4, 5],
            "value": [100, 101, 102, 103, 104],
            "dpid": ["aeos"] * 5,
        })
    elif dpid == "cms":
        data = pl.DataFrame({
            "patient_id": [6, 7, 8, 9, 10],
            "value": [200, 201, 202, 203, 204],
            "dpid": ["cms"] * 5,
        })
    elif dpid == "kpsc":
        data = pl.DataFrame({
            "patient_id": [11, 12, 13, 14, 15],
            "value": [300, 301, 302, 303, 304],
            "dpid": ["kpsc"] * 5,
        })
    else:
        data = pl.DataFrame({
            "patient_id": [],
            "value": [],
            "dpid": [],
        })

    return data.lazy()


@pytest.fixture
def dpid_map_fixture() -> pl.DataFrame:
    """Create a sample dpid_map for testing."""
    return pl.DataFrame({
        "dpid": ["aeos", "cms", "kpsc"],
        "surrogate_id": [1, 2, 3],
    })


class TestAggregateTableBasic:
    """Example-based tests for aggregate_table."""

    def test_aggregate_table_stacked_has_dpid(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Stacked output preserves dpid column with real values."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader,
        )

        stacked = result["stacked"]
        assert "dpid" in stacked.columns
        dpids = stacked["dpid"].unique().to_list()
        assert set(dpids) == {"aeos", "cms"}

    def test_aggregate_table_masked_has_surrogate(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Masked output has surrogate_id, no dpid."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader,
        )

        masked = result["masked"]
        assert "surrogate_id" in masked.columns
        assert "dpid" not in masked.columns
        assert masked.height > 0

    def test_aggregate_table_stacked_and_masked_same_row_count(
        self, dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Stacked and masked have same row count."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader,
        )

        assert result["stacked"].height == result["masked"].height
        assert result["stacked"].height == 10  # 5 rows from aeos + 5 from cms

    def test_aggregate_table_single_dp(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Single DP input produces correct output."""
        table_inputs = [
            TableInput("kpsc", "wp041", Path("/data/kpsc/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader,
        )

        assert result["stacked"].height == 5
        assert result["masked"].height == 5
        assert result["stacked"]["dpid"][0] == "kpsc"

    def test_aggregate_table_empty_inputs(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Empty input produces empty DataFrames with correct schema."""
        table_inputs: list[TableInput] = []

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader,
        )

        assert result["stacked"].height == 0
        assert result["masked"].height == 0
        # Check schema columns exist
        assert "dpid" in result["stacked"].columns
        assert "surrogate_id" in result["masked"].columns

    def test_aggregate_table_preserves_other_columns(
        self, dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Aggregation preserves columns other than dpid/surrogate_id."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader,
        )

        stacked = result["stacked"]
        # Should have original columns plus dpid
        assert "patient_id" in stacked.columns
        assert "value" in stacked.columns
        assert "dpid" in stacked.columns

    def test_aggregate_table_three_dps(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Three DPs each with 5 rows produces 15-row stacked output."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
            TableInput("kpsc", "wp041", Path("/data/kpsc/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader,
        )

        assert result["stacked"].height == 15
        assert result["masked"].height == 15


class TestAggregateTableSchemaDrift:
    """Tests for schema drift handling."""

    def test_aggregate_table_with_schema_drift(
        self, dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Handles schema drift gracefully using diagonal concat."""

        def fake_reader_drift(msoc_path: Path, table_name: str, dpid: str) -> pl.LazyFrame:
            if dpid == "aeos":
                # Has extra_col
                data = pl.DataFrame({
                    "patient_id": [1, 2],
                    "value": [100, 101],
                    "dpid": ["aeos"] * 2,
                    "extra_col": ["x", "y"],
                })
            else:
                # No extra_col
                data = pl.DataFrame({
                    "patient_id": [3, 4],
                    "value": [200, 201],
                    "dpid": ["cms"] * 2,
                })

            return data.lazy()

        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map_fixture,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            fake_reader_drift,
        )

        stacked = result["stacked"]
        assert stacked.height == 4
        # extra_col should exist and be null for cms rows
        assert "extra_col" in stacked.columns
        # Check that cms rows have null extra_col
        cms_rows = stacked.filter(pl.col("dpid") == "cms")
        assert cms_rows["extra_col"].is_null().sum() == 2
