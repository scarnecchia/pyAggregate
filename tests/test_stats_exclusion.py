"""Tests for _stats exclusion logic in rollup."""

from pathlib import Path

import polars as pl
import pytest

from pyaggregate.config import AggTypeConfig
from pyaggregate.core.input_resolution import TableInput
from pyaggregate.core.pipeline import aggregate_table, should_exclude_rollup


class TestShouldExcludeRollup:
    """Tests for should_exclude_rollup function."""

    def test_exclude_rollup_matches_stats_pattern(self) -> None:
        """Table matching *_stats pattern is excluded."""
        assert should_exclude_rollup("ae_stats", ("*_stats",))

    def test_exclude_rollup_no_match(self) -> None:
        """Table not matching pattern is not excluded."""
        assert not should_exclude_rollup("ae", ("*_stats",))

    def test_exclude_rollup_multiple_patterns(self) -> None:
        """Table matching any pattern is excluded."""
        assert should_exclude_rollup("lab_results", ("*_stats", "lab_*"))
        assert should_exclude_rollup("ae_stats", ("*_stats", "lab_*"))

    def test_exclude_rollup_empty_patterns(self) -> None:
        """Empty exclusion patterns exclude nothing."""
        assert not should_exclude_rollup("ae_stats", ())
        assert not should_exclude_rollup("ae", ())

    def test_exclude_rollup_complex_pattern(self) -> None:
        """Support fnmatch patterns with wildcards."""
        assert should_exclude_rollup("test_stats", ("*_stats",))
        assert should_exclude_rollup("ae_summary_stats", ("*_stats",))
        assert should_exclude_rollup("proc_data", ("proc_*",))


class TestAggregateTableExcludeRollup:
    """Tests for aggregate_table with exclusion logic."""

    def fake_reader(self, msoc_path: Path, table_name: str, dpid: str) -> pl.LazyFrame:
        """Create synthetic LazyFrame for testing."""
        if dpid == "aeos":
            data = pl.DataFrame(
                {
                    "value": [100, 200],
                    "dpid": ["aeos"] * 2,
                }
            )
        else:
            data = pl.DataFrame(
                {
                    "value": [],
                    "dpid": [],
                }
            )
        return data.lazy()

    @pytest.fixture
    def dpid_map(self) -> pl.DataFrame:
        """Create a sample dpid_map for testing."""
        return pl.DataFrame(
            {
                "dpid": ["aeos"],
                "surrogate_id": ["dp_001"],
            }
        )

    def test_aggregate_table_excluded_table_no_rollup(self, dpid_map: pl.DataFrame) -> None:
        """Table matching exclusion pattern does not have rollup output."""
        agg_config = AggTypeConfig(
            name="qa",
            source_reqtype="qar",
            exclude_from_rollup=("*_stats",),
        )
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "ae_stats",
            self.fake_reader,
        )

        assert "stacked" in result
        assert "masked" in result
        assert "rollup" not in result

    def test_aggregate_table_non_excluded_table_has_rollup(self, dpid_map: pl.DataFrame) -> None:
        """Table not matching exclusion pattern has rollup output."""
        agg_config = AggTypeConfig(
            name="qa",
            source_reqtype="qar",
            exclude_from_rollup=("*_stats",),
        )
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "ae",
            self.fake_reader,
        )

        assert "stacked" in result
        assert "masked" in result
        assert "rollup" in result

    def test_aggregate_table_no_exclusions_all_have_rollup(self, dpid_map: pl.DataFrame) -> None:
        """With empty exclusion list, all tables get rollup."""
        agg_config = AggTypeConfig(
            name="qa",
            source_reqtype="qar",
            exclude_from_rollup=(),
        )
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "ae_stats",
            self.fake_reader,
        )

        assert "rollup" in result

    def test_aggregate_table_multiple_exclusion_patterns(self, dpid_map: pl.DataFrame) -> None:
        """Multiple patterns all work for exclusion."""
        agg_config = AggTypeConfig(
            name="qa",
            source_reqtype="qar",
            exclude_from_rollup=("*_stats", "lab_*"),
        )
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        # Test exclusion of ae_stats
        result_stats = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "ae_stats",
            self.fake_reader,
        )
        assert "rollup" not in result_stats

        # Test exclusion of lab_results
        result_lab = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "lab_results",
            self.fake_reader,
        )
        assert "rollup" not in result_lab

        # Test non-exclusion of ae
        result_ae = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "ae",
            self.fake_reader,
        )
        assert "rollup" in result_ae
