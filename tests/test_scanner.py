"""Tests for filesystem scanner and catalog population."""

from dataclasses import dataclass
from pathlib import Path

from pyaggregate.config import AppConfig, OutputConfig, ScanConfig, StateConfig
from pyaggregate.io.catalog_store import CatalogStore
from pyaggregate.io.scanner import run_scan, run_scan_dry


@dataclass
class TreeSpec:
    """Specification for a single package in the tree."""

    dpid: str
    reqtype: str
    wpid: str
    verid: str
    has_msoc: bool
    has_scdm: bool = False


def build_request_tree(tmp_path: Path, specs: list[TreeSpec]) -> tuple[Path, Path]:
    """Build a realistic requests tree from a specification.

    Args:
        tmp_path: Temporary directory root
        specs: List of TreeSpec entries

    Returns:
        Tuple of (requests_root, catalog_db)
    """
    requests_root = tmp_path / "requests"
    catalog_db = tmp_path / "test.db"

    for spec in specs:
        # Map reqtype to directory (qar -> qa, qmr -> qm)
        qa_or_qm = "qa" if spec.reqtype == "qar" else "qm"
        version_dir_name = f"soc_{spec.reqtype}_{spec.wpid}_{spec.dpid}_{spec.verid}"
        workplan_dir = (
            requests_root / qa_or_qm / spec.dpid / "packages" / f"soc_{spec.reqtype}_{spec.wpid}"
        )
        version_dir = workplan_dir / version_dir_name

        version_dir.mkdir(parents=True, exist_ok=True)

        if spec.has_msoc:
            msoc_dir = version_dir / "msoc"
            msoc_dir.mkdir(parents=True, exist_ok=True)

            if spec.has_scdm:
                scdm_dir = msoc_dir / "scdm_snapshot"
                scdm_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Create msoc_new to simulate failed QA
            (version_dir / "msoc_new").mkdir(parents=True, exist_ok=True)

    return requests_root, catalog_db


def create_config(requests_root: Path, catalog_db: Path, tmp_path: Path) -> AppConfig:
    """Create test AppConfig."""
    return AppConfig(
        scan=ScanConfig(requests_root=requests_root),
        state=StateConfig(
            catalog_db=catalog_db,
            log_dir=tmp_path / "logs",
        ),
        output=OutputConfig(output_root=tmp_path / "output"),
        agg_types={},
    )


class TestScannerBasics:
    """Basic scanner functionality."""

    def test_scan_single_package_with_msoc(self, tmp_path: Path) -> None:
        """AC2.1: Scanner picks up a package with msoc."""
        specs = [TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True)]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        with CatalogStore(catalog_db) as store:
            store.init_schema()
            result = run_scan(config, store)

        assert result.rows_upserted == 1
        assert result.packages_skipped == 0
        assert result.errors == 0

        with CatalogStore(catalog_db) as store:
            df = store.snapshot_catalog()
            assert len(df) == 1
            row = df.row(0, named=True)
            assert row["dpid"] == "aeos"
            assert row["wpid"] == "wp041"
            assert row["reqtype"] == "qar"
            assert row["verid"] == "v01"
            assert "msoc" in row["msoc_path"]

    def test_scan_multiple_versions_picks_latest(self, tmp_path: Path) -> None:
        """AC2.1: With multiple versions, scanner picks highest verid."""
        specs = [
            TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True),
            TreeSpec("aeos", "qar", "wp041", "v02", has_msoc=True),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        with CatalogStore(catalog_db) as store:
            store.init_schema()
            result = run_scan(config, store)

        assert result.rows_upserted == 1
        assert result.packages_skipped == 0

        with CatalogStore(catalog_db) as store:
            df = store.snapshot_catalog()
            assert len(df) == 1
            row = df.row(0, named=True)
            assert row["verid"] == "v02"

    def test_scan_skips_msoc_new_only(self, tmp_path: Path) -> None:
        """AC2.2: Package with only msoc_new/ (no msoc/) creates no row."""
        specs = [
            TreeSpec("aeos", "qar", "wp042", "v01", has_msoc=False),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        with CatalogStore(catalog_db) as store:
            store.init_schema()
            result = run_scan(config, store)

        assert result.rows_upserted == 0
        assert result.packages_skipped == 1

        with CatalogStore(catalog_db) as store:
            df = store.snapshot_catalog()
            assert len(df) == 0

    def test_scan_scdm_snapshot_detection(self, tmp_path: Path) -> None:
        """AC2.4: has_scdm=1 when scdm_snapshot/ exists, 0 otherwise."""
        specs = [
            TreeSpec("cms", "qar", "wp041", "v01", has_msoc=True, has_scdm=True),
            TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True, has_scdm=False),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        with CatalogStore(catalog_db) as store:
            store.init_schema()
            result = run_scan(config, store)

        assert result.rows_upserted == 2

        with CatalogStore(catalog_db) as store:
            df = store.snapshot_catalog()
            assert len(df) == 2

            # Find the rows
            cms_row = None
            aeos_row = None
            for i in range(len(df)):
                row = df.row(i, named=True)
                if row["dpid"] == "cms":
                    cms_row = row
                elif row["dpid"] == "aeos":
                    aeos_row = row

            assert cms_row is not None
            assert cms_row["has_scdm"] == 1

            assert aeos_row is not None
            assert aeos_row["has_scdm"] == 0

    def test_scan_unparseable_directory_logged_and_skipped(self, tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
        """AC2.5: Unparseable directory name logged at WARN, scan continues."""
        import logging

        specs = [
            TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)

        # Add an unparseable directory (missing verid)
        bad_workplan = requests_root / "qa" / "aeos" / "packages" / "soc_qar_wp041"
        bad_version_dir = bad_workplan / "soc_qar_wp041_aeos"
        bad_version_dir.mkdir(parents=True, exist_ok=True)
        (bad_version_dir / "msoc").mkdir(parents=True, exist_ok=True)

        config = create_config(requests_root, catalog_db, tmp_path)

        with caplog.at_level(logging.WARNING):
            with CatalogStore(catalog_db) as store:
                store.init_schema()
                result = run_scan(config, store)

        # Should have 1 upserted and logged the bad directory
        assert result.rows_upserted == 1
        assert result.errors == 0

        # Verify WARN log was emitted with the unparseable directory name
        assert any(
            "unparseable package directory" in record.message
            and record.levelno == logging.WARNING
            for record in caplog.records
        )

        with CatalogStore(catalog_db) as store:
            df = store.snapshot_catalog()
            assert len(df) == 1


class TestScannerIdempotence:
    """Test idempotence property (AC2.3)."""

    def test_scan_idempotence_no_changes_on_rerun(self, tmp_path: Path) -> None:
        """AC2.3: Running scanner twice produces same snapshot (except observed_at)."""
        specs = [
            TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True),
            TreeSpec("cms", "qmr", "wp042", "v02", has_msoc=True),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        # First scan
        with CatalogStore(catalog_db) as store:
            store.init_schema()
            result1 = run_scan(config, store)
            snap1 = store.snapshot_catalog()

        assert result1.rows_upserted == 2

        # Second scan
        with CatalogStore(catalog_db) as store:
            result2 = run_scan(config, store)
            snap2 = store.snapshot_catalog()

        assert result2.rows_upserted == 2

        # Verify snapshots are identical except observed_at
        assert len(snap1) == len(snap2)

        cols_to_check = ["dpid", "wpid", "reqtype", "verid", "msoc_path", "has_scdm"]
        snap1_subset = snap1.select(cols_to_check).sort("dpid")
        snap2_subset = snap2.select(cols_to_check).sort("dpid")

        # Should be identical
        assert snap1_subset.equals(snap2_subset)


class TestScannerDryRun:
    """Test dry-run mode."""

    def test_dry_run_no_db_writes(self, tmp_path: Path) -> None:
        """Dry run should not modify database."""
        specs = [
            TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        with CatalogStore(catalog_db) as store:
            store.init_schema()

        # Dry run
        with CatalogStore(catalog_db) as store:
            changes = run_scan_dry(config, store)

        assert len(changes) > 0

        # Verify DB is still empty
        with CatalogStore(catalog_db) as store:
            df = store.snapshot_catalog()
            assert len(df) == 0


class TestScannerMultipleDPIDs:
    """Test scanning multiple DPIDs."""

    def test_scan_multiple_dpids(self, tmp_path: Path) -> None:
        """Scan correctly catalogs multiple DPIDs and creates surrogates."""
        specs = [
            TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True),
            TreeSpec("cms", "qar", "wp041", "v01", has_msoc=True),
            TreeSpec("fake_dp", "qmr", "wp051", "v01", has_msoc=True),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        with CatalogStore(catalog_db) as store:
            store.init_schema()
            result = run_scan(config, store)

        assert result.rows_upserted == 3

        with CatalogStore(catalog_db) as store:
            cat = store.snapshot_catalog()
            dpid_map = store.snapshot_dpid_map()

            assert len(cat) == 3
            assert len(dpid_map) == 3

            # Verify all DPIDs are in the catalog
            dpids = set(cat["dpid"].to_list())
            assert dpids == {"aeos", "cms", "fake_dp"}

            # Verify all DPIDs are in dpid_map
            mapped_dpids = set(dpid_map["dpid"].to_list())
            assert mapped_dpids == {"aeos", "cms", "fake_dp"}

            # Verify surrogate IDs are sequential
            surrogates = sorted(dpid_map["surrogate_id"].to_list())
            assert surrogates == ["dp_001", "dp_002", "dp_003"]

    def test_scan_multiple_dpids_with_multiple_workplans(self, tmp_path: Path) -> None:
        """Scan multiple DPIDs with multiple workplans per DPID."""
        specs = [
            # aeos with 2 workplans, 3 reqtypes
            TreeSpec("aeos", "qar", "wp041", "v01", has_msoc=True),
            TreeSpec("aeos", "qar", "wp042", "v01", has_msoc=True),
            TreeSpec("aeos", "qmr", "wp041", "v01", has_msoc=True),
            # cms with 2 workplans
            TreeSpec("cms", "qar", "wp041", "v01", has_msoc=True),
            TreeSpec("cms", "qmr", "wp051", "v01", has_msoc=True),
            # fake_dp with 1 workplan
            TreeSpec("fake_dp", "qar", "wp041", "v01", has_msoc=True),
        ]
        requests_root, catalog_db = build_request_tree(tmp_path, specs)
        config = create_config(requests_root, catalog_db, tmp_path)

        with CatalogStore(catalog_db) as store:
            store.init_schema()
            result = run_scan(config, store)

        assert result.rows_upserted == 6
        assert result.packages_skipped == 0

        with CatalogStore(catalog_db) as store:
            cat = store.snapshot_catalog()
            dpid_map = store.snapshot_dpid_map()

            assert len(cat) == 6
            assert len(dpid_map) == 3

            # Verify all 3 DPIDs
            dpids = set(cat["dpid"].to_list())
            assert dpids == {"aeos", "cms", "fake_dp"}

            # Count entries per DPID
            aeos_count = len(cat.filter(cat["dpid"] == "aeos"))
            cms_count = len(cat.filter(cat["dpid"] == "cms"))
            fake_count = len(cat.filter(cat["dpid"] == "fake_dp"))

            assert aeos_count == 3
            assert cms_count == 2
            assert fake_count == 1
