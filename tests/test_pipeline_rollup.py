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

    def test_compute_rollup_removes_dpid(self) -> None:
        """Rollup output does not contain dpid column."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "aeos", "cms"],
            "region": ["CA", "CA", "CA"],
            "count": [10, 20, 30],
        })

        rollup = compute_rollup(stacked, None, None)

        assert "dpid" not in rollup.columns

    def test_compute_rollup_removes_surrogate_id(self) -> None:
        """Rollup output does not contain surrogate_id column."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "aeos"],
            "surrogate_id": [1, 1],
            "region": ["CA", "CA"],
            "count": [10, 20],
        })

        rollup = compute_rollup(stacked, None, None)

        assert "surrogate_id" not in rollup.columns

    def test_compute_rollup_preserves_sum(self) -> None:
        """Sum of numeric columns in rollup equals sum in stacked."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "aeos", "cms"],
            "region": ["CA", "CA", "CA"],
            "count": [10, 20, 30],
            "value": [100.0, 200.0, 300.0],
        })

        rollup = compute_rollup(stacked, None, None)

        assert rollup["count"].sum() == pytest.approx(60)
        assert rollup["value"].sum() == pytest.approx(600.0)

    def test_compute_rollup_collapses_identical_keys(self) -> None:
        """Identical key combinations collapse to single row."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "cms", "kpsc"],
            "region": ["CA", "CA", "CA"],
            "count": [10, 20, 30],
        })

        rollup = compute_rollup(stacked, None, None)

        # All rows have same key, should collapse to 1
        assert rollup.height == 1
        assert rollup["count"][0] == 60

    def test_compute_rollup_distinct_keys_preserved(self) -> None:
        """Distinct key combinations create separate rows."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "cms", "kpsc"],
            "region": ["CA", "TX", "NY"],
            "count": [10, 20, 30],
        })

        rollup = compute_rollup(stacked, None, None)

        # Each region is distinct, should have 3 rows
        assert rollup.height == 3

    def test_compute_rollup_custom_keys(self) -> None:
        """Custom rollup_keys uses only specified columns."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "aeos", "cms"],
            "region": ["CA", "CA", "TX"],
            "state": ["CA", "CA", "TX"],
            "count": [10, 20, 30],
        })

        rollup = compute_rollup(stacked, ["region"], None)

        assert "region" in rollup.columns
        assert "state" not in rollup.columns

    def test_compute_rollup_custom_aggs(self) -> None:
        """Custom rollup_aggs applies specified aggregation functions."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "aeos", "cms"],
            "region": ["CA", "CA", "CA"],
            "count": [10, 20, 30],
            "value": [100.0, 200.0, 300.0],
        })

        rollup = compute_rollup(
            stacked,
            None,
            {"count": "sum", "value": "mean"},
        )

        assert rollup["count"][0] == 60
        assert rollup["value"][0] == pytest.approx(200.0)

    def test_compute_rollup_default_aggs_sum(self) -> None:
        """Default aggregation is sum for numeric columns."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "cms"],
            "count": [10, 20],
        })

        rollup = compute_rollup(stacked, None, None)

        assert rollup["count"][0] == 30

    def test_compute_rollup_default_keys_all_non_numeric(self) -> None:
        """Default keys are all non-numeric columns after drops."""
        stacked = pl.DataFrame({
            "dpid": ["aeos", "aeos"],
            "surrogate_id": [1, 2],
            "region": ["CA", "TX"],
            "count": [10, 20],
        })

        rollup = compute_rollup(stacked, None, None)

        # dpid and surrogate_id are dropped
        # Keys should be: region (the only non-numeric col)
        assert "region" in rollup.columns
        # With distinct regions, should not collapse
        assert rollup.height == 2


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
        stacked = pl.DataFrame({
            "dpid": [r[0] for r in rows],
            "region": [r[1] for r in rows],
            "value": [r[2] for r in rows],
        })

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
        stacked = pl.DataFrame({
            "dpid": [r[0] for r in rows],
            "value": [r[1] for r in rows],
        })
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
    def test_rollup_no_dpid_leakage(self, rows) -> None:
        """dpid and surrogate_id never appear in rollup output."""
        stacked = pl.DataFrame({
            "dpid": [r[0] for r in rows],
            "value": [r[1] for r in rows],
        })

        rollup = compute_rollup(stacked, None, None)

        assert "dpid" not in rollup.columns
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
        """Rollup columns are stacked columns minus dpid and surrogate_id."""
        stacked = pl.DataFrame({
            "dpid": [r[0] for r in rows],
            "region": [r[1] for r in rows],
            "value": [r[2] for r in rows],
        })

        rollup = compute_rollup(stacked, None, None)

        rollup_cols = set(rollup.columns)
        stacked_cols = set(stacked.columns) - {"dpid", "surrogate_id"}

        assert rollup_cols == stacked_cols


class TestAggregateTableWithRollup:
    """Tests for aggregate_table extended with rollup output."""

    def fake_reader(self, msoc_path: Path, table_name: str, dpid: str) -> pl.LazyFrame:
        """Create synthetic LazyFrame for testing."""
        if dpid == "aeos":
            data = pl.DataFrame({
                "patient_id": [1, 2],
                "value": [100, 200],
                "dpid": ["aeos"] * 2,
            })
        elif dpid == "cms":
            data = pl.DataFrame({
                "patient_id": [3, 4],
                "value": [300, 400],
                "dpid": ["cms"] * 2,
            })
        else:
            data = pl.DataFrame({
                "patient_id": [],
                "value": [],
                "dpid": [],
            })
        return data.lazy()

    @pytest.fixture
    def dpid_map(self) -> pl.DataFrame:
        """Create a sample dpid_map for testing."""
        return pl.DataFrame({
            "dpid": ["aeos", "cms"],
            "surrogate_id": [1, 2],
        })

    def test_aggregate_table_includes_rollup_in_output(self, dpid_map: pl.DataFrame) -> None:
        """aggregate_table output dict includes 'rollup' key."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            self.fake_reader,
        )

        assert "rollup" in result
        assert "stacked" in result
        assert "masked" in result

    def test_aggregate_table_rollup_has_correct_properties(
        self, dpid_map: pl.DataFrame
    ) -> None:
        """Rollup output has no dpid/surrogate_id and sums match."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            self.fake_reader,
        )

        rollup = result["rollup"]
        stacked = result["stacked"]

        assert "dpid" not in rollup.columns
        assert "surrogate_id" not in rollup.columns
        assert rollup["value"].sum() == pytest.approx(stacked["value"].sum())

    def test_aggregate_table_rollup_row_count_lte_stacked(
        self, dpid_map: pl.DataFrame
    ) -> None:
        """Rollup row count is less than or equal to stacked."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        result = aggregate_table(
            table_inputs,
            dpid_map,
            AggTypeConfig(name="qa", source_reqtype="qar"),
            "patient",
            self.fake_reader,
        )

        assert result["rollup"].height <= result["stacked"].height

    def test_aggregate_table_applies_config_rollup_keys(
        self, dpid_map: pl.DataFrame
    ) -> None:
        """Config-driven custom rollup_keys are applied to rollup computation."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
            TableInput("cms", "wp041", Path("/data/cms/msoc"), "qar"),
        ]

        # Create config with custom rollup_keys for 'patient' table
        table_overrides = MappingProxyType({
            "patient": TableOverride(rollup_keys=("patient_id",), rollup_aggs=None),
        })
        agg_config = AggTypeConfig(
            name="qa",
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

    def test_aggregate_table_applies_config_rollup_aggs(
        self, dpid_map: pl.DataFrame
    ) -> None:
        """Config-driven custom rollup_aggs are applied to rollup computation."""
        table_inputs = [
            TableInput("aeos", "wp041", Path("/data/aeos/msoc"), "qar"),
        ]

        # Create config with custom aggregation (mean instead of sum)
        table_overrides = MappingProxyType({
            "patient": TableOverride(rollup_keys=None, rollup_aggs={"value": "mean"}),
        })
        agg_config = AggTypeConfig(
            name="qa",
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
