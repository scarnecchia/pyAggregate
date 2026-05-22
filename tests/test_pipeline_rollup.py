"""Tests for pipeline rollup aggregation."""

from pathlib import Path
from types import MappingProxyType

import polars as pl
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from pyaggregate.config import AggTypeConfig, TableOverride
from pyaggregate.core.input_resolution import TableInput
from pyaggregate.core.pipeline import aggregate_table, compute_rollup


class TestComputeRollupBasic:
    """Example-based tests for compute_rollup function."""

    def test_compute_rollup_removes_dp(self) -> None:
        """Rollup output does not contain `dp` column."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "aeos", "cms"],
                "region": ["CA", "CA", "CA"],
                "count": [10, 20, 30],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert "dp" not in rollup.columns

    def test_compute_rollup_removes_surrogate_id(self) -> None:
        """Rollup output does not contain surrogate_id column."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "aeos"],
                "surrogate_id": ["dp_001", "dp_001"],
                "region": ["CA", "CA"],
                "count": [10, 20],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert "surrogate_id" not in rollup.columns

    def test_compute_rollup_preserves_sum(self) -> None:
        """Sum of numeric columns in rollup equals sum in stacked."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "aeos", "cms"],
                "region": ["CA", "CA", "CA"],
                "count": [10, 20, 30],
                "value": [100.0, 200.0, 300.0],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert rollup["count"].sum() == pytest.approx(60)
        assert rollup["value"].sum() == pytest.approx(600.0)

    def test_compute_rollup_collapses_identical_keys(self) -> None:
        """Identical key combinations collapse to single row."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms", "kpsc"],
                "region": ["CA", "CA", "CA"],
                "count": [10, 20, 30],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        # All rows have same key, should collapse to 1
        assert rollup.height == 1
        assert rollup["count"][0] == 60

    def test_compute_rollup_distinct_keys_preserved(self) -> None:
        """Distinct key combinations create separate rows."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms", "kpsc"],
                "region": ["CA", "TX", "NY"],
                "count": [10, 20, 30],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        # Each region is distinct, should have 3 rows
        assert rollup.height == 3

    def test_compute_rollup_custom_keys(self) -> None:
        """Custom rollup_keys uses only specified columns."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "aeos", "cms"],
                "region": ["CA", "CA", "TX"],
                "state": ["CA", "CA", "TX"],
                "count": [10, 20, 30],
            }
        )

        rollup = compute_rollup(stacked, ["region"], None)

        assert "region" in rollup.columns
        assert "state" not in rollup.columns

    def test_compute_rollup_custom_aggs(self) -> None:
        """Custom rollup_aggs applies specified aggregation functions."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "aeos", "cms"],
                "region": ["CA", "CA", "CA"],
                "count": [10, 20, 30],
                "value": [100.0, 200.0, 300.0],
            }
        )

        rollup = compute_rollup(
            stacked,
            None,
            {"count": "sum", "value": "mean"},
        )

        assert rollup["count"][0] == 60
        assert rollup["value"][0] == pytest.approx(200.0)

    def test_compute_rollup_default_aggs_sum(self) -> None:
        """Default aggregation is sum for numeric columns."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms"],
                "count": [10, 20],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert rollup["count"][0] == 30

    def test_compute_rollup_default_keys_all_non_numeric(self) -> None:
        """Default keys are all non-numeric columns after drops."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "aeos"],
                "surrogate_id": ["dp_001", "dp_002"],
                "region": ["CA", "TX"],
                "count": [10, 20],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        # dp and surrogate_id are dropped
        # Keys should be: region (the only non-numeric col)
        assert "region" in rollup.columns
        # With distinct regions, should not collapse
        assert rollup.height == 2


class TestComputeRollupNumericFiltering:
    """Tests for date-dtype and distribution-statistic name filtering."""

    def test_date_columns_become_group_keys(self) -> None:
        """Date-typed columns are not summed; they participate as group keys."""
        from datetime import date

        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms"],
                "mindate": [date(2024, 1, 1), date(2024, 1, 1)],
                "maxdate": [date(2024, 12, 31), date(2024, 12, 31)],
                "count": [10, 20],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert "mindate" in rollup.columns
        assert "maxdate" in rollup.columns
        # Same date pair across both partners collapses to one row, count sums to 30
        assert rollup.height == 1
        assert rollup["count"][0] == 30
        # Date columns retain their Date dtype (not summed to numbers)
        assert rollup.schema["mindate"] == pl.Date
        assert rollup.schema["maxdate"] == pl.Date

    def test_distinct_dates_preserve_rows(self) -> None:
        """Distinct date values across partners produce separate rows."""
        from datetime import date

        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms"],
                "mindate": [date(2024, 1, 1), date(2024, 6, 1)],
                "count": [10, 20],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert rollup.height == 2

    def test_percentile_columns_not_summed(self) -> None:
        """Distribution-stat columns (p1/p25/median/max) are not summed."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms"],
                "variable": ["age", "age"],
                "p1": [1.0, 2.0],
                "median": [45.0, 50.0],
                "max": [90.0, 95.0],
                "count": [10, 20],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        # `count` is the only summable numeric; the rest become group keys
        # Each row has distinct (variable, p1, median, max) so 2 rows out
        assert rollup.height == 2
        assert "p1" in rollup.columns
        assert "median" in rollup.columns
        assert "max" in rollup.columns
        # Sums must equal the inputs, not collapse
        assert sorted(rollup["count"].to_list()) == [10, 20]

    def test_distribution_stats_case_insensitive(self) -> None:
        """NEVER_SUM matching is case-insensitive (Mean, MEDIAN, etc.)."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms"],
                "variable": ["age", "age"],
                "Mean": [40.0, 50.0],
                "MEDIAN": [45.0, 50.0],
                "n": [10, 20],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        # Mean/MEDIAN are NEVER_SUM by case-insensitive match
        assert "Mean" in rollup.columns
        assert "MEDIAN" in rollup.columns
        # Only `n` should be summed
        assert rollup.height == 2

    def test_summable_count_columns_are_aggregated(self) -> None:
        """Count-like columns (count, n, allrec) still sum normally."""
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "aeos", "cms"],
                "tabid": ["enc", "enc", "enc"],
                "count": [10, 20, 30],
                "n": [1, 2, 3],
                "allrec": [100, 200, 300],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        # Single tabid -> collapses to one row, all numeric sums preserved
        assert rollup.height == 1
        assert rollup["count"][0] == 60
        assert rollup["n"][0] == 6
        assert rollup["allrec"][0] == 600

    def test_id_count_columns_still_sum(self) -> None:
        """Per-partner ID-count columns (patid, encounterid) are summed.

        These are counts of unique IDs per partner per the QA data dictionary,
        not IDs themselves, so summing them across partners is correct.
        """
        stacked = pl.DataFrame(
            {
                "dp": ["aeos", "cms"],
                "tabid": ["enc", "enc"],
                "patid": [1000.0, 2000.0],
                "encounterid": [5000.0, 7000.0],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert rollup.height == 1
        assert rollup["patid"][0] == 3000.0
        assert rollup["encounterid"][0] == 12000.0


class TestComputeRollupPropertyBased:
    """Property-based tests using hypothesis."""

    @given(
        st.lists(
            st.tuples(
                st.sampled_from(["aeos", "cms", "kpsc"]),
                st.sampled_from(["CA", "TX", "NY"]),
                st.integers(min_value=0, max_value=100),
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @example([("aeos", "CA", 10), ("aeos", "CA", 20), ("cms", "CA", 30)])
    @example([("aeos", "CA", 10)])
    @example([("aeos", "CA", 10), ("aeos", "TX", 20), ("cms", "NY", 30)])
    def test_rollup_row_count_invariant(self, rows) -> None:
        """Row count of rollup is less than or equal to stacked."""
        stacked = pl.DataFrame(
            {
                "dp": [r[0] for r in rows],
                "region": [r[1] for r in rows],
                "value": [r[2] for r in rows],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert rollup.height <= stacked.height

    @given(
        st.lists(
            st.tuples(
                st.sampled_from(["aeos", "cms", "kpsc"]),
                st.integers(min_value=1, max_value=100),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @example([("aeos", 10)])
    @example([("aeos", 10), ("aeos", 20), ("aeos", 30)])
    @example([("aeos", 100), ("cms", 200), ("kpsc", 300)])
    def test_rollup_sum_preservation(self, rows) -> None:
        """Sum of numeric columns preserved from stacked to rollup."""
        stacked = pl.DataFrame(
            {
                "dp": [r[0] for r in rows],
                "value": [r[1] for r in rows],
            }
        )
        stacked_sum = stacked["value"].sum()

        rollup = compute_rollup(stacked, None, None)
        rollup_sum = rollup["value"].sum()

        assert rollup_sum == pytest.approx(stacked_sum)

    @given(
        st.lists(
            st.tuples(
                st.sampled_from(["aeos", "cms"]),
                st.integers(min_value=1, max_value=100),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @example([("aeos", 10)])
    @example([("aeos", 10), ("cms", 20)])
    def test_rollup_no_dp_leakage(self, rows) -> None:
        """dp and surrogate_id never appear in rollup output."""
        stacked = pl.DataFrame(
            {
                "dp": [r[0] for r in rows],
                "value": [r[1] for r in rows],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        assert "dp" not in rollup.columns
        assert "surrogate_id" not in rollup.columns

    @given(
        st.lists(
            st.tuples(
                st.just("aeos"),
                st.sampled_from(["CA", "TX", "NY"]),
                st.integers(min_value=1, max_value=100),
            ),
            min_size=1,
            max_size=30,
        )
    )
    @example([("aeos", "CA", 10)])
    @example([("aeos", "CA", 10), ("aeos", "CA", 20)])
    @example([("aeos", "CA", 10), ("aeos", "TX", 20), ("aeos", "NY", 30)])
    def test_rollup_schema_stability(self, rows) -> None:
        """Rollup columns are stacked columns minus dp and surrogate_id."""
        stacked = pl.DataFrame(
            {
                "dp": [r[0] for r in rows],
                "region": [r[1] for r in rows],
                "value": [r[2] for r in rows],
            }
        )

        rollup = compute_rollup(stacked, None, None)

        rollup_cols = set(rollup.columns)
        stacked_cols = set(stacked.columns) - {"dp", "surrogate_id"}

        assert rollup_cols == stacked_cols


class TestAggregateTableWithRollup:
    """Tests for aggregate_table extended with rollup output."""

    def fake_reader(self, msoc_path: Path, table_name: str, dpid: str) -> pl.LazyFrame:
        """Create synthetic LazyFrame for testing."""
        if dpid == "aeos":
            data = pl.DataFrame(
                {
                    "patient_id": [1, 2],
                    "value": [100, 200],
                    "dp": ["aeos"] * 2,
                }
            )
        elif dpid == "cms":
            data = pl.DataFrame(
                {
                    "patient_id": [3, 4],
                    "value": [300, 400],
                    "dp": ["cms"] * 2,
                }
            )
        else:
            data = pl.DataFrame(
                {
                    "patient_id": [],
                    "value": [],
                    "dp": [],
                }
            )
        return data.lazy()

    @pytest.fixture
    def dpid_map(self) -> pl.DataFrame:
        """Create a sample dpid_map for testing."""
        return pl.DataFrame(
            {
                "dpid": ["aeos", "cms"],
                "surrogate_id": ["dp_001", "dp_002"],
            }
        )

    def test_aggregate_table_includes_rollup_in_output(self, dpid_map: pl.DataFrame) -> None:
        """aggregate_table output dict includes 'rollup' key."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            AggTypeConfig(name="qa", output_path=Path("/tmp"), source_reqtype="qar"),
            "patient",
            self.fake_reader,
        )

        assert "rollup" in result
        assert "stacked" in result
        assert "masked" in result

    def test_aggregate_table_rollup_has_correct_properties(self, dpid_map: pl.DataFrame) -> None:
        """Rollup output has no dp/surrogate_id and sums match."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            AggTypeConfig(name="qa", output_path=Path("/tmp"), source_reqtype="qar"),
            "patient",
            self.fake_reader,
        )

        rollup = result["rollup"]
        stacked = result["stacked"]

        assert "dp" not in rollup.columns
        assert "surrogate_id" not in rollup.columns
        assert rollup["value"].sum() == pytest.approx(stacked["value"].sum())

    def test_aggregate_table_rollup_row_count_lte_stacked(self, dpid_map: pl.DataFrame) -> None:
        """Rollup row count is less than or equal to stacked."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            AggTypeConfig(name="qa", output_path=Path("/tmp"), source_reqtype="qar"),
            "patient",
            self.fake_reader,
        )

        assert result["rollup"].height <= result["stacked"].height

    def test_aggregate_table_applies_config_rollup_keys(self, dpid_map: pl.DataFrame) -> None:
        """Config-driven custom rollup_keys are applied to rollup computation."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        # Create config with custom rollup_keys for 'patient' table
        table_overrides = MappingProxyType(
            {
                "patient": TableOverride(rollup_keys=("patient_id",), rollup_aggs=None),
            }
        )
        agg_config = AggTypeConfig(
            name="qa",
            output_path=Path("/tmp"),
            source_reqtype="qar",
            table_overrides=table_overrides,
        )

        result = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "patient",
            self.fake_reader,
        )

        rollup = result["rollup"]
        # With patient_id as key, should have 4 rows (patient_ids 1, 2, 3, 4)
        assert rollup.height == 4
        assert "patient_id" in rollup.columns
        assert "value" in rollup.columns

    def test_aggregate_table_applies_config_rollup_aggs(self, dpid_map: pl.DataFrame) -> None:
        """Config-driven custom rollup_aggs are applied to rollup computation."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        # Create config with custom aggregation (mean instead of sum)
        table_overrides = MappingProxyType(
            {
                "patient": TableOverride(rollup_keys=None, rollup_aggs={"value": "mean"}),
            }
        )
        agg_config = AggTypeConfig(
            name="qa",
            output_path=Path("/tmp"),
            source_reqtype="qar",
            table_overrides=table_overrides,
        )

        result = aggregate_table(
            table_inputs,
            dpid_map,
            agg_config,
            "patient",
            self.fake_reader,
        )

        rollup = result["rollup"]
        # With custom agg (mean), value should be average of [100, 200]
        assert rollup["value"][0] == pytest.approx(150.0)
