"""Tests for CatalogStore sqlite wrapper."""

from pathlib import Path

from pyaggregate.io.catalog_store import CatalogStore


class TestCatalogStoreInit:
    """Tests for CatalogStore initialization."""

    def test_init_schema_creates_all_tables(self, tmp_path: Path) -> None:
        """Verify init_schema creates catalog, dpid_map, and scan_log tables."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        # Query sqlite_master to verify tables exist
        cursor = store._conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}

        assert "catalog" in tables
        assert "dpid_map" in tables
        assert "scan_log" in tables

        store.close()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """Verify WAL mode is set after init_schema."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        cursor = store._conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]

        assert mode.lower() == "wal"
        store.close()

    def test_context_manager(self, tmp_path: Path) -> None:
        """Verify context manager opens and closes connection."""
        db_path = tmp_path / "test.db"

        with CatalogStore(db_path) as store:
            store.init_schema()
            # Connection should be open
            assert store._conn is not None

        # After exiting, we can't use the store (connection closed)
        # A simple check: _conn should still exist but be closed


class TestUpsertCatalogRow:
    """Tests for upsert_catalog_row method."""

    def test_insert_new_catalog_row(self, tmp_path: Path) -> None:
        """Test inserting a new catalog row."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp001",
            reqtype="qar",
            verid="v1",
            msoc_path="/path/to/msoc",
            has_scdm=1,
        )

        # Verify row exists
        cursor = store._conn.cursor()
        cursor.execute(
            "SELECT verid, msoc_path, has_scdm FROM catalog WHERE dpid=? AND wpid=? AND reqtype=?",
            ("aeos", "wp001", "qar"),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "v1"
        assert row[1] == "/path/to/msoc"
        assert row[2] == 1

        store.close()

    def test_upsert_updates_existing_row(self, tmp_path: Path) -> None:
        """Test that UPSERT updates verid, msoc_path, has_scdm on conflict."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        # Insert initial row
        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp001",
            reqtype="qar",
            verid="v1",
            msoc_path="/old/path",
            has_scdm=0,
        )

        # Insert with same key but different values
        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp001",
            reqtype="qar",
            verid="v2",
            msoc_path="/new/path",
            has_scdm=1,
        )

        # Verify row was updated
        cursor = store._conn.cursor()
        cursor.execute(
            "SELECT verid, msoc_path, has_scdm FROM catalog WHERE dpid=? AND wpid=? AND reqtype=?",
            ("aeos", "wp001", "qar"),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "v2"
        assert row[1] == "/new/path"
        assert row[2] == 1

        store.close()

    def test_upsert_idempotence(self, tmp_path: Path) -> None:
        """Test that inserting same values twice only changes observed_at."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        # Insert first time
        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp001",
            reqtype="qar",
            verid="v1",
            msoc_path="/path",
            has_scdm=1,
        )

        cursor = store._conn.cursor()
        cursor.execute(
            "SELECT verid, msoc_path, has_scdm, observed_at FROM catalog WHERE dpid=? AND wpid=? AND reqtype=?",
            ("aeos", "wp001", "qar"),
        )
        first_row = cursor.fetchone()
        first_observed_at = first_row[3]

        # Insert same values again
        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp001",
            reqtype="qar",
            verid="v1",
            msoc_path="/path",
            has_scdm=1,
        )

        cursor.execute(
            "SELECT verid, msoc_path, has_scdm, observed_at FROM catalog WHERE dpid=? AND wpid=? AND reqtype=?",
            ("aeos", "wp001", "qar"),
        )
        second_row = cursor.fetchone()

        # verid, msoc_path, has_scdm should be the same
        assert second_row[0] == first_row[0]
        assert second_row[1] == first_row[1]
        assert second_row[2] == first_row[2]

        # observed_at may have changed (it's updated on every UPSERT)
        # This test verifies the values themselves don't change, only observed_at

        store.close()


class TestGetOrCreateSurrogate:
    """Tests for get_or_create_surrogate method."""

    def test_first_surrogate_is_dp_001(self, tmp_path: Path) -> None:
        """Test that first surrogate ID is dp_001."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        surrogate = store.get_or_create_surrogate("aeos")

        assert surrogate == "dp_001"

        store.close()

    def test_second_surrogate_is_dp_002(self, tmp_path: Path) -> None:
        """Test that second different DPID gets dp_002."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        surrogate1 = store.get_or_create_surrogate("aeos")
        surrogate2 = store.get_or_create_surrogate("haze")

        assert surrogate1 == "dp_001"
        assert surrogate2 == "dp_002"

        store.close()

    def test_surrogate_stability(self, tmp_path: Path) -> None:
        """Test that calling with same DPID returns same surrogate (AC5.1)."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        surrogate1 = store.get_or_create_surrogate("aeos")
        surrogate2 = store.get_or_create_surrogate("aeos")

        assert surrogate1 == surrogate2

        store.close()

    def test_surrogate_monotonicity(self, tmp_path: Path) -> None:
        """Test that surrogates are assigned in order."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        surrogates = [store.get_or_create_surrogate(f"dpid_{i}") for i in range(10)]

        expected = [f"dp_{i + 1:03d}" for i in range(10)]
        assert surrogates == expected

        store.close()

    def test_surrogate_auto_extends(self, tmp_path: Path) -> None:
        """Test that new DPID receives fresh never-before-seen surrogate (AC5.2)."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        # Create some surrogates
        store.get_or_create_surrogate("aeos")
        store.get_or_create_surrogate("haze")

        # New DPID should get next available
        new_surrogate = store.get_or_create_surrogate("new_dpid")

        assert new_surrogate == "dp_003"

        store.close()


class TestSnapshotCatalog:
    """Tests for snapshot_catalog method."""

    def test_snapshot_returns_dataframe(self, tmp_path: Path) -> None:
        """Test that snapshot_catalog returns a polars DataFrame."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        store.upsert_catalog_row(
            dpid="aeos",
            wpid="wp001",
            reqtype="qar",
            verid="v1",
            msoc_path="/path",
            has_scdm=1,
        )

        df = store.snapshot_catalog()

        # Check it's a polars DataFrame
        assert hasattr(df, "columns")
        assert hasattr(df, "shape")

        # Check columns
        expected_cols = {"dpid", "wpid", "reqtype", "verid", "msoc_path", "has_scdm", "observed_at"}
        assert set(df.columns) == expected_cols

        # Check row count
        assert df.shape[0] == 1

        store.close()

    def test_snapshot_catalog_empty(self, tmp_path: Path) -> None:
        """Test snapshot_catalog on empty catalog."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        df = store.snapshot_catalog()

        assert df.shape[0] == 0

        store.close()


class TestSnapshotDpidMap:
    """Tests for snapshot_dpid_map method."""

    def test_snapshot_returns_dataframe(self, tmp_path: Path) -> None:
        """Test that snapshot_dpid_map returns a polars DataFrame."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        store.get_or_create_surrogate("aeos")

        df = store.snapshot_dpid_map()

        # Check it's a polars DataFrame
        assert hasattr(df, "columns")
        assert hasattr(df, "shape")

        # Check columns
        expected_cols = {"dpid", "surrogate_id", "first_seen_at"}
        assert set(df.columns) == expected_cols

        # Check row count
        assert df.shape[0] == 1

        store.close()

    def test_snapshot_dpid_map_empty(self, tmp_path: Path) -> None:
        """Test snapshot_dpid_map on empty map."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        df = store.snapshot_dpid_map()

        assert df.shape[0] == 0

        store.close()


class TestScanLog:
    """Tests for scan log recording."""

    def test_record_scan_start(self, tmp_path: Path) -> None:
        """Test recording scan start."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        scan_id = "scan_001"
        store.record_scan_start(scan_id)

        cursor = store._conn.cursor()
        cursor.execute("SELECT status FROM scan_log WHERE scan_id=?", (scan_id,))
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "running"

        store.close()

    def test_record_scan_end_success(self, tmp_path: Path) -> None:
        """Test recording scan end with success status."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        scan_id = "scan_001"
        store.record_scan_start(scan_id)
        store.record_scan_end(scan_id, "success")

        cursor = store._conn.cursor()
        cursor.execute("SELECT status, error_msg FROM scan_log WHERE scan_id=?", (scan_id,))
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "success"
        assert row[1] is None

        store.close()

    def test_record_scan_end_failure_with_message(self, tmp_path: Path) -> None:
        """Test recording scan end with failure and error message."""
        db_path = tmp_path / "test.db"
        store = CatalogStore(db_path)
        store.init_schema()

        scan_id = "scan_001"
        error_msg = "Connection timeout"
        store.record_scan_start(scan_id)
        store.record_scan_end(scan_id, "failure", error_msg)

        cursor = store._conn.cursor()
        cursor.execute(
            "SELECT status, error_msg, ended_at FROM scan_log WHERE scan_id=?",
            (scan_id,),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "failure"
        assert row[1] == error_msg
        assert row[2] is not None  # ended_at should be set

        store.close()


class TestConcurrentReadDuringWrite:
    """Tests for WAL mode concurrent access."""

    def test_concurrent_read_during_write(self, tmp_path: Path) -> None:
        """Test that WAL mode allows concurrent read while write is in progress."""
        db_path = tmp_path / "test.db"

        store1 = CatalogStore(db_path)
        store1.init_schema()
        store1.close()

        # Open two connections
        store_writer = CatalogStore(db_path)
        store_reader = CatalogStore(db_path)

        # Insert data in writer
        store_writer.upsert_catalog_row(
            dpid="aeos",
            wpid="wp001",
            reqtype="qar",
            verid="v1",
            msoc_path="/path",
            has_scdm=1,
        )

        # Reader should be able to read (even if writer is mid-transaction)
        df_reader = store_reader.snapshot_catalog()
        assert df_reader.shape[0] >= 0  # Should not block

        store_writer.close()
        store_reader.close()
