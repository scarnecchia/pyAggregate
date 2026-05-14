# pattern: Imperative Shell
"""Filesystem scanner that walks requests tree and populates catalog."""

import fcntl
import logging
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pyaggregate.config import AppConfig
from pyaggregate.core.paths import (
    RequestId,
    parse_request_id,
    pick_latest_approved,
)
from pyaggregate.io.catalog_store import CatalogStore

logger = logging.getLogger(__name__)


@dataclass
class ScanLock:
    """Holds a scan lock file object."""

    fd_obj: object

    def release(self) -> None:
        """Release the lock."""
        try:
            fcntl.flock(self.fd_obj, fcntl.LOCK_UN)  # type: ignore
        except Exception as e:
            logger.error("failed to unlock: %s", e)
        finally:
            self.fd_obj.close()  # type: ignore


@contextmanager
def acquire_scan_lock(lock_path: Path) -> Iterator[bool]:
    """Context manager for acquiring exclusive non-blocking flock.

    Opens <lock_path> for writing and attempts to acquire an exclusive
    non-blocking lock via fcntl.flock(). Yields True if lock acquired,
    False if already held by another process.

    Args:
        lock_path: Path to lock file

    Yields:
        True if lock was acquired, False if already held
    """
    fd_obj = None
    lock = None
    try:
        fd_obj = open(lock_path, "w")  # noqa: SIM115
        try:
            fcntl.flock(fd_obj, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock = ScanLock(fd_obj)
            yield True
        except BlockingIOError:
            yield False
    except Exception as e:
        logger.error("failed to acquire lock: %s", e)
        yield False
    finally:
        if lock is not None:
            lock.release()
        elif fd_obj is not None:
            fd_obj.close()


@dataclass(frozen=True)
class ScanResult:
    """Result of a scan operation."""

    rows_upserted: int
    packages_skipped: int
    errors: int


def run_scan(config: AppConfig, store: CatalogStore) -> ScanResult:
    """Walk requests tree and populate catalog with latest approved msoc.

    Acquires an exclusive non-blocking lock first. If lock is already held,
    logs a message and returns early with 0 rows upserted.

    Args:
        config: Application configuration with requests_root
        store: CatalogStore for database operations

    Returns:
        ScanResult with counts of upserted rows, skipped packages, errors
    """
    lock_path = config.state.catalog_db.with_suffix(".scan.lock")

    with acquire_scan_lock(lock_path) as acquired:
        if not acquired:
            logger.info("scan already in progress")
            return ScanResult(
                rows_upserted=0,
                packages_skipped=0,
                errors=0,
            )

        scan_id = str(uuid4())
        store.record_scan_start(scan_id)

        rows_upserted = 0
        packages_skipped = 0
        errors = 0

        try:
            rows_upserted, packages_skipped, errors = _scan_requests_tree(config, store)
            store.record_scan_end(scan_id, "success")
        except Exception as e:
            logger.exception("scan failed: %s", e)
            store.record_scan_end(scan_id, "failure", str(e))
            errors += 1

        return ScanResult(
            rows_upserted=rows_upserted,
            packages_skipped=packages_skipped,
            errors=errors,
        )


def _walk_requests_tree(requests_root: Path) -> Iterator[tuple[RequestId, Path, bool]]:
    """Walk requests tree and yield (RequestId, version_dir, has_msoc) tuples.

    Only yields entries with successfully parsed RequestIds.
    Logs warnings for unparseable directory names but continues scanning.

    Args:
        requests_root: Root of the requests directory tree

    Yields:
        Tuples of (RequestId, Path to version directory, has_msoc bool)
    """
    if not requests_root.exists():
        return

    for qa_or_qm in ["qa", "qm"]:
        qa_qm_dir = requests_root / qa_or_qm
        if not qa_qm_dir.exists():
            continue

        for dpid_dir in qa_qm_dir.iterdir():
            if not dpid_dir.is_dir():
                continue

            packages_dir = dpid_dir / "packages"
            if not packages_dir.exists():
                continue

            for workplan_dir in packages_dir.iterdir():
                if not workplan_dir.is_dir():
                    continue

                for version_dir in workplan_dir.iterdir():
                    if not version_dir.is_dir():
                        continue

                    rid = parse_request_id(version_dir.name)
                    if rid is None:
                        logger.warning(
                            "skipping unparseable directory: %s",
                            version_dir.name,
                        )
                        continue

                    msoc_path = version_dir / "msoc"
                    has_msoc = msoc_path.exists()
                    yield rid, version_dir, has_msoc


def run_scan_dry(config: AppConfig, store: CatalogStore) -> list[str]:
    """Perform dry-run scan: walk tree and report intended changes.

    Does not write to database. Reports the winning version for each
    (dpid, wpid, reqtype) group using the same ranking logic as run_scan.

    Args:
        config: Application configuration
        store: CatalogStore (used for reading only, not writing)

    Returns:
        List of strings describing intended changes
    """
    changes: list[str] = []
    requests_root = config.scan.requests_root

    if not requests_root.exists():
        return changes

    # Group by (dpid, wpid, reqtype)
    grouped: dict[tuple[str, str, str], list[tuple[RequestId, Path, bool]]] = defaultdict(list)

    for rid, version_dir, has_msoc in _walk_requests_tree(requests_root):
        key = (rid.dpid, rid.wpid, rid.reqtype)
        grouped[key].append((rid, version_dir, has_msoc))

    # For each group, pick the latest approved version
    for (_dpid, _wpid, _reqtype), entries in grouped.items():
        rid_entries = [(rid, has_msoc) for rid, _version_dir, has_msoc in entries]
        winning_rid = pick_latest_approved(rid_entries)

        if winning_rid is None:
            continue

        # Find the version_dir for the winning RequestId
        winning_version_dir = None
        for rid, version_dir, _ in entries:
            if rid == winning_rid:
                winning_version_dir = version_dir
                break

        if winning_version_dir is None:
            continue

        msoc_path = winning_version_dir / "msoc"
        has_scdm_dir = msoc_path / "scdm_snapshot"
        has_scdm = 1 if has_scdm_dir.exists() else 0

        changes.append(
            f"would upsert: {winning_rid.dpid}/{winning_rid.wpid}/{winning_rid.reqtype} "
            f"-> {winning_rid.verid} (has_scdm={has_scdm})"
        )

    return changes


def _scan_requests_tree(config: AppConfig, store: CatalogStore) -> tuple[int, int, int]:
    """Internal: walk tree and populate catalog.

    Groups versions by (dpid, wpid, reqtype) and uses pick_latest_approved
    to find the winning version for each group.

    Args:
        config: Application configuration
        store: CatalogStore for database operations

    Returns:
        Tuple of (rows_upserted, packages_skipped, errors)
    """
    rows_upserted = 0
    packages_skipped = 0
    errors = 0

    requests_root = config.scan.requests_root
    if not requests_root.exists():
        logger.warning("requests_root does not exist: %s", requests_root)
        return rows_upserted, packages_skipped, errors

    # Group by (dpid, wpid, reqtype) to find latest approved version
    grouped: dict[tuple[str, str, str], list[tuple[RequestId, Path, bool]]] = defaultdict(list)

    for rid, version_dir, has_msoc in _walk_requests_tree(requests_root):
        key = (rid.dpid, rid.wpid, rid.reqtype)
        grouped[key].append((rid, version_dir, has_msoc))

    # For each group, pick the latest approved version
    for (_dpid, _wpid, _reqtype), entries in grouped.items():
        rid_entries = [(rid, has_msoc) for rid, _version_dir, has_msoc in entries]
        winning_rid = pick_latest_approved(rid_entries)

        if winning_rid is None:
            # No approved version found
            packages_skipped += 1
            continue

        # Find the version_dir for the winning RequestId
        winning_version_dir = None
        for rid, version_dir, _ in entries:
            if rid == winning_rid:
                winning_version_dir = version_dir
                break

        if winning_version_dir is None:
            packages_skipped += 1
            continue

        # Check for scdm_snapshot
        msoc_path = winning_version_dir / "msoc"
        has_scdm_dir = msoc_path / "scdm_snapshot"
        has_scdm = 1 if has_scdm_dir.exists() else 0

        # UPSERT the catalog row
        store.upsert_catalog_row(
            dpid=winning_rid.dpid,
            wpid=winning_rid.wpid,
            reqtype=winning_rid.reqtype,
            verid=winning_rid.verid,
            msoc_path=str(msoc_path),
            has_scdm=has_scdm,
        )

        # Ensure DPID is in dpid_map
        store.get_or_create_surrogate(winning_rid.dpid)

        rows_upserted += 1

    return rows_upserted, packages_skipped, errors
