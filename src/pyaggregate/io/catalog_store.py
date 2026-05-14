# pattern: Imperative Shell
"""SQLite-backed catalog and dpid_map store with UPSERT and surrogate mapping."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import polars as pl


class CatalogStore:
    """Wraps sqlite connection and exposes catalog/dpid_map read/write API."""

    def __init__(self, db_path: Path) -> None:
        """Initialize catalog store with sqlite connection.

        Args:
            db_path: Path to sqlite database file
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")

    def __enter__(self) -> "CatalogStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    def init_schema(self) -> None:
        """Create catalog, dpid_map, and scan_log tables if not present."""
        cursor = self._conn.cursor()

        # Create catalog table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog (
                dpid        TEXT NOT NULL,
                wpid        TEXT NOT NULL,
                reqtype     TEXT NOT NULL,
                verid       TEXT NOT NULL,
                msoc_path   TEXT NOT NULL,
                has_scdm    INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                PRIMARY KEY (dpid, wpid, reqtype)
            )
            """
        )

        # Create dpid_map table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS dpid_map (
                dpid          TEXT PRIMARY KEY,
                surrogate_id  TEXT NOT NULL UNIQUE,
                first_seen_at TEXT NOT NULL
            )
            """
        )

        # Create scan_log table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_log (
                scan_id     TEXT PRIMARY KEY,
                started_at  TEXT NOT NULL,
                ended_at    TEXT,
                status      TEXT NOT NULL,
                error_msg   TEXT
            )
            """
        )

        self._conn.commit()

    def upsert_catalog_row(
        self,
        dpid: str,
        wpid: str,
        reqtype: str,
        verid: str,
        msoc_path: str,
        has_scdm: int,
    ) -> None:
        """UPSERT a catalog row with current UTC timestamp.

        Updates verid, msoc_path, has_scdm, and observed_at on conflict.

        Args:
            dpid: Device or project identifier
            wpid: Work package identifier
            reqtype: Request type (e.g., 'qar', 'qmr')
            verid: Version identifier
            msoc_path: Path to MSOC artifact
            has_scdm: 1 if SCDM data present, 0 otherwise
        """
        observed_at = datetime.now(UTC).isoformat()

        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO catalog (dpid, wpid, reqtype, verid, msoc_path, has_scdm, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dpid, wpid, reqtype)
            DO UPDATE SET
                verid=excluded.verid,
                msoc_path=excluded.msoc_path,
                has_scdm=excluded.has_scdm,
                observed_at=excluded.observed_at
            """,
            (dpid, wpid, reqtype, verid, msoc_path, has_scdm, observed_at),
        )

        self._conn.commit()

    def get_or_create_surrogate(self, dpid: str) -> str:
        """Get or create surrogate ID for DPID.

        Returns existing surrogate if DPID already mapped. Otherwise generates
        next sequential surrogate (dp_001, dp_002, ...) and inserts into dpid_map.

        Transaction isolation ensures monotonic assignment even with concurrent writers.

        Args:
            dpid: Device/project identifier

        Returns:
            Surrogate ID in format dp_NNN (zero-padded to 3 digits)
        """
        cursor = self._conn.cursor()

        # Check if DPID already exists
        cursor.execute("SELECT surrogate_id FROM dpid_map WHERE dpid=?", (dpid,))
        row = cursor.fetchone()
        if row is not None:
            return row[0]

        # Acquire immediate transaction to prevent concurrent surrogate generation
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            # Re-check inside transaction (another writer may have inserted)
            cursor.execute("SELECT surrogate_id FROM dpid_map WHERE dpid=?", (dpid,))
            row = cursor.fetchone()
            if row is not None:
                self._conn.commit()
                return row[0]

            # Calculate next surrogate: max existing + 1
            cursor.execute(
                "SELECT COALESCE(MAX(CAST(SUBSTR(surrogate_id, 4) AS INTEGER)), 0) + 1 "
                "FROM dpid_map"
            )
            next_num = cursor.fetchone()[0]
            surrogate_id = f"dp_{next_num:03d}"

            # Insert new mapping
            first_seen_at = datetime.now(UTC).isoformat()
            cursor.execute(
                "INSERT INTO dpid_map (dpid, surrogate_id, first_seen_at) VALUES (?, ?, ?)",
                (dpid, surrogate_id, first_seen_at),
            )

            self._conn.commit()
            return surrogate_id
        except Exception:
            self._conn.rollback()
            raise

    def snapshot_catalog(self) -> pl.DataFrame:
        """Read entire catalog table into polars DataFrame.

        Returns:
            Point-in-time snapshot of catalog as DataFrame
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM catalog")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        return pl.DataFrame(rows, schema=columns, orient="row")

    def snapshot_dpid_map(self) -> pl.DataFrame:
        """Read entire dpid_map table into polars DataFrame.

        Returns:
            Point-in-time snapshot of dpid_map as DataFrame
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM dpid_map")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        return pl.DataFrame(rows, schema=columns, orient="row")

    def record_scan_start(self, scan_id: str) -> None:
        """Record start of a scan in scan_log.

        Args:
            scan_id: Unique identifier for this scan
        """
        started_at = datetime.now(UTC).isoformat()
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO scan_log (scan_id, started_at, status) VALUES (?, ?, ?)",
            (scan_id, started_at, "running"),
        )
        self._conn.commit()

    def record_scan_end(
        self,
        scan_id: str,
        status: Literal["success", "failure"],
        error_msg: str | None = None,
    ) -> None:
        """Record end of a scan in scan_log.

        Args:
            scan_id: Unique identifier for this scan
            status: Final status ('success' or 'failure')
            error_msg: Optional error message if status is 'failure'
        """
        ended_at = datetime.now(UTC).isoformat()
        cursor = self._conn.cursor()
        cursor.execute(
            "UPDATE scan_log SET ended_at=?, status=?, error_msg=? WHERE scan_id=?",
            (ended_at, status, error_msg, scan_id),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the sqlite connection."""
        if self._conn:
            self._conn.close()
