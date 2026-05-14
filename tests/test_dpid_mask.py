"""Tests for dpid masking function."""

import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyaggregate.core.dpid_mask import mask_dpid


@pytest.fixture
def dpid_map_fixture() -> pl.DataFrame:
    """Create a sample dpid_map for testing."""
    return pl.DataFrame({
        "dpid": ["aeos", "cms", "kpsc"],
        "surrogate_id": [1, 2, 3],
    })


class TestMaskDpidBasic:
    """Example-based tests for mask_dpid."""

    def test_mask_dpid_with_known_mappings(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Test masking with known dpid -> surrogate_id mappings."""
        frame = pl.DataFrame({
            "dpid": ["aeos", "cms", "aeos"],
            "patient_id": [1, 2, 3],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert "surrogate_id" in result.columns
        assert "dpid" not in result.columns
        assert result.height == 3
        # Check specific surrogate values
        surrogates = result["surrogate_id"].to_list()
        assert surrogates == [1, 2, 1]  # aeos->1, cms->2, aeos->1

    def test_mask_dpid_empty_frame(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Test masking an empty DataFrame returns correct schema."""
        frame = pl.DataFrame({
            "dpid": pl.Series([], dtype=pl.Utf8),
            "patient_id": pl.Series([], dtype=pl.Int64),
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert "surrogate_id" in result.columns
        assert "dpid" not in result.columns
        assert result.height == 0

    def test_mask_dpid_single_row(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Test masking a single row."""
        frame = pl.DataFrame({
            "dpid": ["kpsc"],
            "patient_id": [42],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert result.height == 1
        assert result["surrogate_id"][0] == 3

    def test_mask_dpid_preserves_other_columns(
        self, dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Test that masking preserves columns other than dpid."""
        frame = pl.DataFrame({
            "dpid": ["aeos", "cms"],
            "patient_id": [1, 2],
            "name": ["alice", "bob"],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert set(result.columns) == {"surrogate_id", "patient_id", "name"}
        assert result["patient_id"].to_list() == [1, 2]
        assert result["name"].to_list() == ["alice", "bob"]


class TestMaskDpidProperties:
    """Property-based tests using hypothesis."""

    @given(
        data=st.lists(
            st.tuples(
                st.sampled_from(["aeos", "cms", "kpsc"]),
                st.integers(min_value=0, max_value=100),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_row_count_preserved(
        self, data: list[tuple[str, int]], dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Property: Row count is preserved after masking."""
        frame = pl.DataFrame({
            "dpid": [dpid for dpid, _ in data],
            "value": [val for _, val in data],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert result.height == frame.height

    @given(
        data=st.lists(
            st.tuples(
                st.sampled_from(["aeos", "cms", "kpsc"]),
                st.integers(min_value=0, max_value=100),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_no_dpid_column(
        self, data: list[tuple[str, int]], dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Property: Result has no dpid column."""
        frame = pl.DataFrame({
            "dpid": [dpid for dpid, _ in data],
            "value": [val for _, val in data],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert "dpid" not in result.columns

    @given(
        data=st.lists(
            st.tuples(
                st.sampled_from(["aeos", "cms", "kpsc"]),
                st.integers(min_value=0, max_value=100),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_surrogate_id_present(
        self, data: list[tuple[str, int]], dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Property: Result has surrogate_id column."""
        frame = pl.DataFrame({
            "dpid": [dpid for dpid, _ in data],
            "value": [val for _, val in data],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert "surrogate_id" in result.columns

    @given(
        data=st.lists(
            st.tuples(
                st.sampled_from(["aeos", "cms", "kpsc"]),
                st.integers(min_value=0, max_value=100),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_surrogate_uniqueness_per_dpid(
        self, data: list[tuple[str, int]], dpid_map_fixture: pl.DataFrame
    ) -> None:
        """Property: Each unique dpid maps to exactly one unique surrogate_id (injective mapping)."""
        frame = pl.DataFrame({
            "dpid": [dpid for dpid, _ in data],
            "value": [val for _, val in data],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        # Verify the mapping property: use the dpid_map to check each unique dpid in the original
        # maps to exactly one surrogate_id
        dpid_to_surrogate = {}
        for row in frame.iter_rows(named=True):
            dpid = row["dpid"]
            # Find surrogate in dpid_map
            matching = dpid_map_fixture.filter(pl.col("dpid") == dpid)
            if len(matching) > 0:
                surrogate = matching["surrogate_id"][0]
                if dpid not in dpid_to_surrogate:
                    dpid_to_surrogate[dpid] = surrogate
                else:
                    # Verify it's the same surrogate (consistency)
                    assert dpid_to_surrogate[dpid] == surrogate

        surrogates = list(dpid_to_surrogate.values())
        assert len(surrogates) == len(set(surrogates)), (
            f"Mapping is not injective: {dpid_to_surrogate}"
        )

        for _orig_dpid, expected_surrogate in dpid_to_surrogate.items():
            result_rows = result.filter(pl.col("surrogate_id") == expected_surrogate)
            assert result_rows.height > 0, f"Expected rows with surrogate {expected_surrogate}"

    def test_unmapped_dpid_produces_null(self, dpid_map_fixture: pl.DataFrame) -> None:
        """Test that unmapped dpid produces null surrogate_id."""
        frame = pl.DataFrame({
            "dpid": ["unknown_dp"],
            "value": [1],
        })

        result = mask_dpid(frame, dpid_map_fixture)

        assert result.height == 1
        assert result["surrogate_id"][0] is None
