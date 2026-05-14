# pattern: Imperative Shell
"""Filesystem scanner that walks requests tree and populates catalog."""

import fcntl
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pyaggregate.config import AppConfig
from pyaggregate.core.paths import pick_latest_approved, parse_request_id
from pyaggregate.io.catalog_store import CatalogStore

logger = logging.getLogger(__name__)


# Global dictionary to keep lock file objects alive
_lock_files: dict[int, object] = {}


def acquire_scan_lock(lock_path: Path) -> int | None:
    """Attempt to acquire exclusive non-blocking flock on lock file.

    Opens <lock_path> for writing and attempts to acquire an exclusive
    non-blocking lock via fcntl.flock(). Returns the file descriptor on
    success, None if the lock is already held by another process.

    Args:
        lock_path: Path to lock file

    Returns:
        File descriptor (int) on success, None if lock already held
    """
    try:
        # Open lock file for writing, create if doesn't exist
        fd_obj = open(lock_path, "w")
        try:
            # Try to acquire exclusive non-blocking lock
            fcntl.flock(fd_obj, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Keep file object alive to maintain lock
            fd_num = fd_obj.fileno()
            _lock_files[fd_num] = fd_obj
            return fd_num
        except BlockingIOError:
            # Lock is held by another process
            fd_obj.close()
            return None
    except Exception as e:
        logger.error("failed to acquire lock: %s", e)
        return None


def release_scan_lock(fd: int) -> None:
    """Release a scan lock held by file descriptor.

    Args:
        fd: File descriptor returned by acquire_scan_lock
    """
    if fd in _lock_files:
        fd_obj = _lock_files.pop(fd)
        try:
            fcntl.flock(fd_obj, fcntl.LOCK_UN)
        except Exception as e:
            logger.error("failed to unlock: %s", e)
        finally:
            fd_obj.close()


@dataclass(frozen=True)
class ScanResult:
    """Result of a scan operation."""

    rows_upserted: int
    packages_skipped: int
    errors: int


def run_scan(config: AppConfig, store: CatalogStore) -> ScanResult:
    """Walk requests tree and populate catalog with latest approved msoc.

    Args:
        config: Application configuration with requests_root
        store: CatalogStore for database operations

    Returns:
        ScanResult with counts of upserted rows, skipped packages, errors
    """
    scan_id = str(uuid4())
    store.record_scan_start(scan_id)

    rows_upserted = 0
    packages_skipped = 0
    errors = 0

    try:
        rows_upserted, packages_skipped, errors = _scan_requests_tree(
            config, store
        )
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


def run_scan_dry(config: AppConfig, store: CatalogStore) -> list[str]:
    """Perform dry-run scan: walk tree and report intended changes.

    Does not write to database.

    Args:
        config: Application configuration
        store: CatalogStore (used for reading only, not writing)

    Returns:
        List of strings describing intended changes
    """
    changes: list[str] = []

    # Walk the requests tree and collect all packages
    requests_root = config.scan.requests_root
    if not requests_root.exists():
        return changes

    # Iterate qa and qm directories
    for qa_or_qm in ["qa", "qm"]:
        qa_qm_dir = requests_root / qa_or_qm
        if not qa_qm_dir.exists():
            continue

        for dpid_dir in qa_qm_dir.iterdir():
            if not dpid_dir.is_dir():
                continue

            dpid = dpid_dir.name
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
                    if msoc_path.exists():
                        has_scdm_dir = msoc_path / "scdm_snapshot"
                        has_scdm = 1 if has_scdm_dir.exists() else 0
                        changes.append(
                            f"would upsert: {rid.dpid}/{rid.wpid}/{rid.reqtype} "
                            f"-> {rid.verid} (has_scdm={has_scdm})"
                        )

    return changes


def _scan_requests_tree(
    config: AppConfig, store: CatalogStore
) -> tuple[int, int, int]:
    """Internal: walk tree and populate catalog.

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
    grouped: dict[tuple[str, str, str], list[tuple[Path, bool]]] = defaultdict(
        list
    )

    # Iterate qa and qm directories
    for qa_or_qm in ["qa", "qm"]:
        qa_qm_dir = requests_root / qa_or_qm
        if not qa_qm_dir.exists():
            continue

        for dpid_dir in qa_qm_dir.iterdir():
            if not dpid_dir.is_dir():
                continue

            dpid = dpid_dir.name
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

                    # Group by (dpid, wpid, reqtype)
                    key = (rid.dpid, rid.wpid, rid.reqtype)
                    grouped[key].append((version_dir, has_msoc))

    # For each group, pick the latest approved version
    for (dpid, wpid, reqtype), entries in grouped.items():
        # Convert to (RequestId, has_msoc) tuples for pick_latest_approved
        rid_entries = [
            (parse_request_id(version_dir.name), has_msoc)
            for version_dir, has_msoc in entries
        ]
        rid_entries = [
            (rid, has_msoc) for rid, has_msoc in rid_entries if rid is not None
        ]

        # Pick the latest approved version
        winning_rid = pick_latest_approved(rid_entries)

        if winning_rid is None:
            # No approved version found
            packages_skipped += 1
            continue

        # Find the version_dir for the winning RequestId
        winning_version_dir = None
        for version_dir, _ in entries:
            if parse_request_id(version_dir.name) == winning_rid:
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
