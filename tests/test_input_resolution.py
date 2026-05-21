"""Tests for input resolution (core and I/O wrapper)."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

from pyaggregate.config import AggTypeConfig
from pyaggregate.core.input_resolution import (
    TableInput,
    detect_snapshot_collisions,
    filter_catalog,
    group_inputs_by_table,
    select_latest_workplan_per_dp,
    wpid_sort_key,
)
from pyaggregate.io.input_resolver import resolve_inputs


@dataclass
class CatalogFixture:
    """Helper for creating test catalogs."""

    def catalog(self) -> pl.DataFrame:
        """Create a sample catalog with multiple DPs and reqtypes."""
        return pl.DataFrame(
            {
                "dpid": ["aeos", "aeos", "cms", "cms"],
                "wpid": ["wp041", "wp041", "wp041", "wp041"],
                "reqtype": ["qar", "qmr", "qar", "qar"],
                "verid": ["v02", "v01", "v01", "v01"],
                "msoc_path": [
                    "/data/aeos/qar/msoc",
                    "/data/aeos/qmr/msoc",
                    "/data/cms/qar/msoc",
                    "/data/cms/qar/msoc",
                ],
                "has_scdm": [1, 1, 0, 1],
                "observed_at": [
                    "2026-05-14T00:00:00",
                    "2026-05-14T00:00:00",
                    "2026-05-14T00:00:00",
                    "2026-05-14T00:00:00",
                ],
            }
        )


@pytest.fixture
def catalog_fixture() -> CatalogFixture:
    """Fixture for catalog creation."""
    return CatalogFixture()


class TestFilterCatalog:
    """Tests for filter_catalog (pure core function)."""

    def test_filter_catalog_qa_config_filters_qar_only(
        self, catalog_fixture: CatalogFixture
    ) -> None:
        """QA config filters to reqtype='qar' only."""
        catalog = catalog_fixture.catalog()
        agg_config = AggTypeConfig(
            name="qa",
            output_path=Path("/tmp"),
            source_reqtype="qar",
        )

        result = filter_catalog(catalog, agg_config)

        reqtypes = result["reqtype"].unique().to_list()
        assert reqtypes == ["qar"]
        assert len(result) == 3  # aeos qar, cms qar (2 rows)

    def test_filter_catalog_qm_config_filters_qmr_only(
        self, catalog_fixture: CatalogFixture
    ) -> None:
        """QM config filters to reqtype='qmr' only."""
        catalog = catalog_fixture.catalog()
        agg_config = AggTypeConfig(
            name="qm",
            output_path=Path("/tmp"),
            source_reqtype="qmr",
        )

        result = filter_catalog(catalog, agg_config)

        reqtypes = result["reqtype"].unique().to_list()
        assert reqtypes == ["qmr"]
        assert len(result) == 1  # aeos qmr

    def test_filter_catalog_snapshot_config_filters_has_scdm(
        self, catalog_fixture: CatalogFixture
    ) -> None:
        """Snapshot config filters to source_field='has_scdm' == 1."""
        catalog = catalog_fixture.catalog()
        agg_config = AggTypeConfig(
            name="snapshot",
            output_path=Path("/tmp"),
            source_field="has_scdm",
        )

        result = filter_catalog(catalog, agg_config)

        has_scdm = result["has_scdm"].unique().to_list()
        assert has_scdm == [1]
        assert len(result) == 3  # aeos qar, aeos qmr, cms qar

    def test_filter_catalog_preserves_all_columns(self, catalog_fixture: CatalogFixture) -> None:
        """Filter preserves all columns from input catalog."""
        catalog = catalog_fixture.catalog()
        agg_config = AggTypeConfig(
            name="qa",
            output_path=Path("/tmp"),
            source_reqtype="qar",
        )

        result = filter_catalog(catalog, agg_config)

        expected_cols = {"dpid", "wpid", "reqtype", "verid", "msoc_path", "has_scdm", "observed_at"}
        assert set(result.columns) == expected_cols


class TestWpidSortKey:
    """Tests for wpid_sort_key (pure helper)."""

    def test_numeric_ordering(self) -> None:
        """wp10 sorts after wp9 numerically, not lexicographically."""
        assert wpid_sort_key("wp009") < wpid_sort_key("wp010")

    def test_strips_wp_prefix(self) -> None:
        """Returns the integer value of the numeric portion."""
        assert wpid_sort_key("wp041") == 41
        assert wpid_sort_key("wp001") == 1


class TestSelectLatestWorkplanPerDp:
    """Tests for select_latest_workplan_per_dp (pure core function).

    For each (dpid, reqtype) pair, keeps only the row with the highest wpid.
    Catalog rows for older wpids are dropped at aggregation time, even though
    they remain in the historical catalog.
    """

    def test_picks_highest_wpid_for_dpid_reqtype(self) -> None:
        """Same (dpid, reqtype) across multiple wpids -> only highest wpid survives."""
        catalog = pl.DataFrame(
            {
                "dpid": ["aeos", "aeos", "aeos"],
                "wpid": ["wp041", "wp042", "wp040"],
                "reqtype": ["qar", "qar", "qar"],
                "verid": ["v03", "v01", "v05"],
                "msoc_path": ["/p1", "/p2", "/p3"],
                "has_scdm": [1, 1, 1],
                "observed_at": ["2026-05-14T00:00:00"] * 3,
            }
        )

        result = select_latest_workplan_per_dp(catalog)

        assert len(result) == 1
        row = result.row(0, named=True)
        assert row["wpid"] == "wp042"
        assert row["verid"] == "v01"
        assert row["msoc_path"] == "/p2"

    def test_sorts_wpid_numerically_not_lexicographically(self) -> None:
        """wp010 must beat wp009 (lexicographic would order wp009 > wp010)."""
        catalog = pl.DataFrame(
            {
                "dpid": ["aeos", "aeos"],
                "wpid": ["wp009", "wp010"],
                "reqtype": ["qar", "qar"],
                "verid": ["v01", "v01"],
                "msoc_path": ["/p9", "/p10"],
                "has_scdm": [1, 1],
                "observed_at": ["2026-05-14T00:00:00"] * 2,
            }
        )

        result = select_latest_workplan_per_dp(catalog)

        assert len(result) == 1
        assert result.row(0, named=True)["wpid"] == "wp010"

    def test_qar_and_qmr_winners_are_independent(self) -> None:
        """Within one dpid, qar and qmr each get their own max-wpid winner."""
        catalog = pl.DataFrame(
            {
                "dpid": ["aeos", "aeos", "aeos", "aeos"],
                "wpid": ["wp041", "wp042", "wp041", "wp043"],
                "reqtype": ["qar", "qar", "qmr", "qmr"],
                "verid": ["v01", "v01", "v01", "v01"],
                "msoc_path": ["/qar41", "/qar42", "/qmr41", "/qmr43"],
                "has_scdm": [1, 1, 1, 1],
                "observed_at": ["2026-05-14T00:00:00"] * 4,
            }
        )

        result = select_latest_workplan_per_dp(catalog)

        winners = {
            (row["dpid"], row["reqtype"]): row["wpid"]
            for row in result.iter_rows(named=True)
        }
        assert winners == {("aeos", "qar"): "wp042", ("aeos", "qmr"): "wp043"}

    def test_different_dpids_do_not_compete(self) -> None:
        """Each dpid's winner is computed independently of other dpids."""
        catalog = pl.DataFrame(
            {
                "dpid": ["aeos", "aeos", "cms"],
                "wpid": ["wp041", "wp042", "wp001"],
                "reqtype": ["qar", "qar", "qar"],
                "verid": ["v01", "v01", "v01"],
                "msoc_path": ["/a41", "/a42", "/c01"],
                "has_scdm": [1, 1, 1],
                "observed_at": ["2026-05-14T00:00:00"] * 3,
            }
        )

        result = select_latest_workplan_per_dp(catalog)

        winners = {row["dpid"]: row["wpid"] for row in result.iter_rows(named=True)}
        assert winners == {"aeos": "wp042", "cms": "wp001"}

    def test_preserves_all_columns(self) -> None:
        """Selection preserves every column from the input catalog."""
        catalog = pl.DataFrame(
            {
                "dpid": ["aeos"],
                "wpid": ["wp041"],
                "reqtype": ["qar"],
                "verid": ["v01"],
                "msoc_path": ["/p"],
                "has_scdm": [1],
                "observed_at": ["2026-05-14T00:00:00"],
            }
        )

        result = select_latest_workplan_per_dp(catalog)

        assert set(result.columns) == set(catalog.columns)

    def test_empty_catalog_returns_empty(self) -> None:
        """Empty input -> empty output (same schema)."""
        catalog = pl.DataFrame(
            schema={
                "dpid": pl.Utf8,
                "wpid": pl.Utf8,
                "reqtype": pl.Utf8,
                "verid": pl.Utf8,
                "msoc_path": pl.Utf8,
                "has_scdm": pl.Int64,
                "observed_at": pl.Utf8,
            }
        )

        result = select_latest_workplan_per_dp(catalog)

        assert len(result) == 0
        assert set(result.columns) == set(catalog.columns)


class TestGroupInputsByTable:
    """Tests for group_inputs_by_table (pure core function)."""

    def test_group_inputs_by_table_groups_correctly(self) -> None:
        """Groups inputs by table name."""
        table_listings = [
            ("patient", "aeos", "wp041", Path("/data/aeos/qar/msoc"), "qar"),
            ("diagnosis", "aeos", "wp041", Path("/data/aeos/qar/msoc"), "qar"),
            ("patient", "cms", "wp041", Path("/data/cms/qar/msoc"), "qar"),
        ]

        result = group_inputs_by_table(table_listings)

        assert "patient" in result
        assert "diagnosis" in result
        assert len(result["patient"]) == 2
        assert len(result["diagnosis"]) == 1

    def test_group_inputs_by_table_preserves_metadata(self) -> None:
        """Preserves dpid, wpid, msoc_path, and reqtype in TableInput."""
        table_listings = [
            ("patient", "aeos", "wp041", Path("/data/aeos/qar/msoc"), "qar"),
        ]

        result = group_inputs_by_table(table_listings)

        patient_inputs = result["patient"]
        assert len(patient_inputs) == 1
        input_obj = patient_inputs[0]
        assert input_obj.dpid == "aeos"
        assert input_obj.wpid == "wp041"
        assert input_obj.msoc_path == Path("/data/aeos/qar/msoc")
        assert input_obj.reqtype == "qar"

    def test_group_inputs_by_table_empty_listings(self) -> None:
        """Returns empty dict for empty table listings."""
        result = group_inputs_by_table([])
        assert result == {}

    def test_table_input_is_frozen(self) -> None:
        """TableInput is a frozen dataclass."""
        from dataclasses import FrozenInstanceError

        table_input = TableInput(
            dpid="aeos",
            wpid="wp041",
            msoc_path=Path("/data"),
            reqtype="qar",
        )

        with pytest.raises(FrozenInstanceError):
            table_input.dpid = "cms"  # type: ignore


class TestDetectSnapshotCollisions:
    """Tests for detect_snapshot_collisions (pure core function)."""

    def test_detect_collisions_same_filename_different_reqtype(self) -> None:
        """Detects same filename from both qar and qmr for same (dpid, wpid)."""
        inputs = {
            "patient": [
                TableInput("aeos", "wp041", Path("/data/aeos/qar/msoc"), "qar"),
                TableInput("aeos", "wp041", Path("/data/aeos/qmr/msoc"), "qmr"),
            ],
        }

        warnings = detect_snapshot_collisions(inputs)

        assert len(warnings) > 0
        assert any("collision" in w.lower() for w in warnings)
        assert any("patient" in w for w in warnings)

    def test_detect_collisions_no_collision_different_dpid(self) -> None:
        """No collision when same filename from different dpids."""
        inputs = {
            "patient": [
                TableInput("aeos", "wp041", Path("/data/aeos/qar/msoc"), "qar"),
                TableInput("cms", "wp041", Path("/data/cms/qar/msoc"), "qar"),
            ],
        }

        warnings = detect_snapshot_collisions(inputs)

        assert len(warnings) == 0

    def test_detect_collisions_no_collision_same_reqtype(self) -> None:
        """No collision when same filename from same reqtype."""
        inputs = {
            "patient": [
                TableInput("aeos", "wp041", Path("/data/aeos/qar/msoc"), "qar"),
                TableInput("cms", "wp041", Path("/data/cms/qar/msoc"), "qar"),
            ],
        }

        warnings = detect_snapshot_collisions(inputs)

        assert len(warnings) == 0

    def test_detect_collisions_empty_inputs(self) -> None:
        """Returns empty list for empty inputs."""
        warnings = detect_snapshot_collisions({})
        assert warnings == []


class TestResolveInputs:
    """Tests for resolve_inputs (I/O wrapper function)."""

    def test_resolve_inputs_qa_with_real_files(self, tmp_path: Path) -> None:
        """resolve_inputs globs files and returns grouped inputs for QA."""
        # Set up filesystem structure
        msoc_path = tmp_path / "aeos" / "qar" / "msoc"
        msoc_path.mkdir(parents=True)
        (msoc_path / "patient.sas7bdat").touch()
        (msoc_path / "diagnosis.sas7bdat").touch()

        # Create catalog
        catalog = pl.DataFrame(
            {
                "dpid": ["aeos"],
                "wpid": ["wp041"],
                "reqtype": ["qar"],
                "verid": ["v01"],
                "msoc_path": [str(msoc_path)],
                "has_scdm": [0],
                "observed_at": ["2026-05-14T00:00:00"],
            }
        )

        agg_config = AggTypeConfig(
            name="qa",
            output_path=Path("/tmp"),
            source_reqtype="qar",
        )

        # Mock glob to return our test files
        with patch("pyaggregate.io.input_resolver.glob_tables") as mock_glob:
            mock_glob.return_value = ["patient", "diagnosis"]

            result = resolve_inputs(catalog, agg_config)

        assert "patient" in result
        assert "diagnosis" in result
        assert len(result["patient"]) == 1
        assert result["patient"][0].dpid == "aeos"

    def test_resolve_inputs_snapshot_with_subdirectory(self, tmp_path: Path) -> None:
        """resolve_inputs uses subdirectory config field for snapshot."""
        msoc_path = tmp_path / "aeos" / "qar" / "msoc"
        scdm_dir = msoc_path / "scdm_snapshot"
        scdm_dir.mkdir(parents=True)
        (scdm_dir / "patient.sas7bdat").touch()

        catalog = pl.DataFrame(
            {
                "dpid": ["aeos"],
                "wpid": ["wp041"],
                "reqtype": ["qar"],
                "verid": ["v01"],
                "msoc_path": [str(msoc_path)],
                "has_scdm": [1],
                "observed_at": ["2026-05-14T00:00:00"],
            }
        )

        agg_config = AggTypeConfig(
            name="snapshot",
            output_path=Path("/tmp"),
            source_field="has_scdm",
            subdirectory="scdm_snapshot",
        )

        with patch("pyaggregate.io.input_resolver.glob_scdm_tables") as mock_glob:
            mock_glob.return_value = ["patient"]

            result = resolve_inputs(catalog, agg_config)

        assert "patient" in result

    def test_resolve_inputs_filters_catalog_first(self, tmp_path: Path) -> None:
        """resolve_inputs calls filter_catalog to respect agg_config."""
        msoc_path = tmp_path / "msoc"
        msoc_path.mkdir(parents=True)

        catalog = pl.DataFrame(
            {
                "dpid": ["aeos", "cms"],
                "wpid": ["wp041", "wp041"],
                "reqtype": ["qar", "qmr"],
                "verid": ["v01", "v01"],
                "msoc_path": [str(msoc_path), str(msoc_path)],
                "has_scdm": [1, 1],
                "observed_at": ["2026-05-14T00:00:00", "2026-05-14T00:00:00"],
            }
        )

        agg_config = AggTypeConfig(
            name="qa",
            output_path=Path("/tmp"),
            source_reqtype="qar",
        )

        with patch("pyaggregate.io.input_resolver.glob_tables") as mock_glob:
            mock_glob.return_value = ["patient"]

            result = resolve_inputs(catalog, agg_config)

        # Only qar should be in result (qmr filtered out)
        assert all(input_obj.reqtype == "qar" for inputs in result.values() for input_obj in inputs)

    def test_resolve_inputs_empty_catalog_after_filter(self, tmp_path: Path) -> None:
        """resolve_inputs returns empty dict if catalog has no matching rows."""
        catalog = pl.DataFrame(
            {
                "dpid": ["cms"],
                "wpid": ["wp041"],
                "reqtype": ["qmr"],
                "verid": ["v01"],
                "msoc_path": [str(tmp_path)],
                "has_scdm": [0],
                "observed_at": ["2026-05-14T00:00:00"],
            }
        )

        agg_config = AggTypeConfig(
            name="qa",
            output_path=Path("/tmp"),
            source_reqtype="qar",  # No qar rows in catalog
        )

        result = resolve_inputs(catalog, agg_config)

        assert result == {}
