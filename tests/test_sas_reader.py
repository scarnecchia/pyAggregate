"""Tests for SAS reader wrapper."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl

from pyaggregate.io.sas_reader import (
    glob_scdm_tables,
    glob_tables,
    read_metadata,
    read_table,
)


class TestReadTable:
    """Tests for read_table function."""

    def test_read_table_returns_lazy_frame_with_lowercase_columns(self) -> None:
        """read_table returns LazyFrame with lowercase column names."""
        msoc_path = Path("/fake/msoc")
        table_name = "Patient"
        dpid = "aeos"

        mock_lazy_frame = pl.LazyFrame(
            {
                "PATID": [1, 2],
                "BIRTH_DT": ["2000-01-01", "2001-01-01"],
            }
        )

        with patch("pyaggregate.io.sas_reader.scan_readstat") as mock_scan:
            mock_scan.return_value = mock_lazy_frame

            result = read_table(msoc_path, table_name, dpid)

            assert isinstance(result, pl.LazyFrame)
            collected = result.collect()
            assert "patid" in collected.columns
            assert "birth_dt" in collected.columns
            assert "PATID" not in collected.columns
            assert "BIRTH_DT" not in collected.columns

    def test_read_table_injects_dpid_column(self) -> None:
        """read_table injects dpid column with given value."""
        msoc_path = Path("/fake/msoc")
        table_name = "Patient"
        dpid = "cms"

        mock_lazy_frame = pl.LazyFrame({"PATID": [1, 2]})

        with patch("pyaggregate.io.sas_reader.scan_readstat") as mock_scan:
            mock_scan.return_value = mock_lazy_frame

            result = read_table(msoc_path, table_name, dpid)
            collected = result.collect()

            assert "dpid" in collected.columns
            assert collected["dpid"].to_list() == ["cms", "cms"]

    def test_read_table_constructs_correct_path(self) -> None:
        """read_table constructs path as msoc_path/table_name.sas7bdat."""
        msoc_path = Path("/data/aeos/qar/msoc")
        table_name = "Patient"
        dpid = "aeos"

        mock_lazy_frame = pl.LazyFrame({"PATID": [1]})

        with patch("pyaggregate.io.sas_reader.scan_readstat") as mock_scan:
            mock_scan.return_value = mock_lazy_frame

            read_table(msoc_path, table_name, dpid)

            # Verify scan_readstat was called with correct path
            mock_scan.assert_called_once()
            call_args = mock_scan.call_args
            assert str(msoc_path / f"{table_name}.sas7bdat") in str(call_args)

    def test_read_table_passes_schema_overrides(self) -> None:
        """read_table passes schema_overrides to scan_readstat."""
        msoc_path = Path("/fake/msoc")
        table_name = "Patient"
        dpid = "aeos"
        schema_overrides = {"patid": pl.Int64}

        mock_lazy_frame = pl.LazyFrame({"PATID": [1]})

        with patch("pyaggregate.io.sas_reader.scan_readstat") as mock_scan:
            mock_scan.return_value = mock_lazy_frame

            read_table(msoc_path, table_name, dpid, schema_overrides=schema_overrides)

            call_kwargs = mock_scan.call_args.kwargs
            assert "schema_overrides" in call_kwargs
            assert call_kwargs["schema_overrides"] == schema_overrides

    def test_read_table_defaults_preserve_order_false(self) -> None:
        """read_table defaults preserve_order to False."""
        msoc_path = Path("/fake/msoc")
        table_name = "Patient"
        dpid = "aeos"

        mock_lazy_frame = pl.LazyFrame({"PATID": [1]})

        with patch("pyaggregate.io.sas_reader.scan_readstat") as mock_scan:
            mock_scan.return_value = mock_lazy_frame

            read_table(msoc_path, table_name, dpid)

            call_kwargs = mock_scan.call_args.kwargs
            assert call_kwargs.get("preserve_order") is False


class TestReadMetadata:
    """Tests for read_metadata function."""

    def test_read_metadata_returns_dict(self) -> None:
        """read_metadata returns a dictionary."""
        sas_path = Path("/fake/patient.sas7bdat")

        mock_metadata = {
            "number_rows": 100,
            "number_variables": 5,
            "table": "patient",
        }

        with patch("pyaggregate.io.sas_reader.ScanReadstat") as mock_scan_class:
            mock_instance = MagicMock()
            mock_instance.metadata = mock_metadata
            mock_scan_class.return_value = mock_instance

            result = read_metadata(sas_path)

            assert result == mock_metadata
            mock_scan_class.assert_called_once()

    def test_read_metadata_uses_correct_path(self) -> None:
        """read_metadata constructs path correctly."""
        sas_path = Path("/data/patient.sas7bdat")

        with patch("pyaggregate.io.sas_reader.ScanReadstat") as mock_scan_class:
            mock_instance = MagicMock()
            mock_instance.metadata = {}
            mock_scan_class.return_value = mock_instance

            read_metadata(sas_path)

            call_args = mock_scan_class.call_args
            assert str(sas_path) in str(call_args)


class TestGlobTables:
    """Tests for glob_tables function."""

    def test_glob_tables_lists_sas7bdat_files(self, tmp_path: Path) -> None:
        """glob_tables lists .sas7bdat files in msoc_path."""
        msoc_path = tmp_path / "msoc"
        msoc_path.mkdir()

        (msoc_path / "Patient.sas7bdat").touch()
        (msoc_path / "Diagnosis.sas7bdat").touch()
        (msoc_path / "Procedure.sas7bdat").touch()

        result = glob_tables(msoc_path)

        assert sorted(result) == ["Diagnosis", "Patient", "Procedure"]

    def test_glob_tables_excludes_subdirs(self, tmp_path: Path) -> None:
        """glob_tables excludes files in excluded subdirectories."""
        msoc_path = tmp_path / "msoc"
        msoc_path.mkdir()
        scdm_dir = msoc_path / "scdm_snapshot"
        scdm_dir.mkdir()

        (msoc_path / "Patient.sas7bdat").touch()
        (scdm_dir / "Diagnosis.sas7bdat").touch()

        result = glob_tables(msoc_path)

        assert result == ["Patient"]


    def test_glob_tables_empty_msoc(self, tmp_path: Path) -> None:
        """glob_tables returns empty list for empty msoc_path."""
        msoc_path = tmp_path / "msoc"
        msoc_path.mkdir()

        result = glob_tables(msoc_path)

        assert result == []


class TestGlobScdmTables:
    """Tests for glob_scdm_tables function."""

    def test_glob_scdm_tables_lists_scdm_files(self, tmp_path: Path) -> None:
        """glob_scdm_tables lists .sas7bdat files in scdm_snapshot."""
        msoc_path = tmp_path / "msoc"
        scdm_dir = msoc_path / "scdm_snapshot"
        scdm_dir.mkdir(parents=True)

        (scdm_dir / "Patient.sas7bdat").touch()
        (scdm_dir / "Diagnosis.sas7bdat").touch()

        result = glob_scdm_tables(msoc_path)

        assert sorted(result) == ["Diagnosis", "Patient"]

    def test_glob_scdm_tables_excludes_other_files(self, tmp_path: Path) -> None:
        """glob_scdm_tables ignores non-.sas7bdat files."""
        msoc_path = tmp_path / "msoc"
        scdm_dir = msoc_path / "scdm_snapshot"
        scdm_dir.mkdir(parents=True)

        (scdm_dir / "Patient.sas7bdat").touch()
        (scdm_dir / "README.txt").touch()
        (scdm_dir / "metadata.json").touch()

        result = glob_scdm_tables(msoc_path)

        assert result == ["Patient"]

    def test_glob_scdm_tables_empty_scdm(self, tmp_path: Path) -> None:
        """glob_scdm_tables returns empty list if scdm_snapshot missing."""
        msoc_path = tmp_path / "msoc"
        msoc_path.mkdir()

        result = glob_scdm_tables(msoc_path)

        assert result == []
