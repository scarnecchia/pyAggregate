"""Tests for scanner concurrency guard with flock."""

from pathlib import Path

from pyaggregate.io.scanner import acquire_scan_lock


class TestScanLockAcquisition:
    """Test flock-based scan lock acquisition."""

    def test_acquire_lock_success(self, tmp_path: Path) -> None:
        """Acquire lock on fresh file succeeds."""
        lock_path = tmp_path / "test.lock"

        with acquire_scan_lock(lock_path) as acquired:
            assert acquired is True
            assert lock_path.exists()

    def test_acquire_lock_already_held(self, tmp_path: Path) -> None:
        """Acquire lock when already held returns False."""
        lock_path = tmp_path / "test.lock"

        # First acquisition succeeds
        with acquire_scan_lock(lock_path) as acquired1:
            assert acquired1 is True

            # Second acquisition fails (lock already held)
            with acquire_scan_lock(lock_path) as acquired2:
                assert acquired2 is False

    def test_acquire_lock_after_release(self, tmp_path: Path) -> None:
        """After releasing lock, subsequent acquisition succeeds."""
        lock_path = tmp_path / "test.lock"

        # First acquisition
        with acquire_scan_lock(lock_path) as acquired1:
            assert acquired1 is True

        # Lock released by context manager

        # Second acquisition should succeed (lock released)
        with acquire_scan_lock(lock_path) as acquired2:
            assert acquired2 is True

    def test_acquire_lock_creates_file(self, tmp_path: Path) -> None:
        """Acquire lock creates lock file if it doesn't exist."""
        lock_path = tmp_path / "new_lock.lock"

        assert not lock_path.exists()

        with acquire_scan_lock(lock_path) as acquired:
            assert acquired is True
            assert lock_path.exists()

    def test_acquire_lock_persistent_across_calls(self, tmp_path: Path) -> None:
        """Lock file persists across separate acquisition calls."""
        lock_path = tmp_path / "persistent.lock"

        # First acquisition
        with acquire_scan_lock(lock_path) as acquired1:
            assert acquired1 is True

        # File still exists
        assert lock_path.exists()

        # Second acquisition works
        with acquire_scan_lock(lock_path) as acquired2:
            assert acquired2 is True


class TestScannerLockIntegration:
    """Test scanner integration with lock guard."""

    def test_run_scan_with_lock_held_exits_cleanly(self, tmp_path: Path) -> None:
        """Scanner exits early with log message when lock is already held."""
        from pyaggregate.config import (
            AppConfig,
            ScanConfig,
            StateConfig,
        )
        from pyaggregate.io.catalog_store import CatalogStore
        from pyaggregate.io.scanner import run_scan

        catalog_db = tmp_path / "test.db"
        requests_root = tmp_path / "requests"
        requests_root.mkdir()

        # Create config
        config = AppConfig(
            scan=ScanConfig(requests_root=requests_root),
            state=StateConfig(
                catalog_db=catalog_db,
                log_dir=tmp_path / "logs",
            ),
            agg_types={},
        )

        # Initialize database
        with CatalogStore(catalog_db) as store:
            store.init_schema()

        # Hold the lock
        lock_path = config.state.catalog_db.with_suffix(".scan.lock")
        with acquire_scan_lock(lock_path) as acquired:
            assert acquired is True

            # Attempt scan - should detect lock and return early
            with CatalogStore(catalog_db) as store:
                result = run_scan(config, store)

            # Should return with no rows upserted (locked out)
            assert result.rows_upserted == 0
            assert result.packages_skipped == 0
            assert result.errors == 0
