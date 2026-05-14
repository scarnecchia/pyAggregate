"""Shared fixtures for pyaggregate tests."""

from typing import Any
from unittest.mock import patch

import polars as pl
import pytest


@pytest.fixture
def patch_sas_reader_for_parquet():
    """Patch scan_readstat to read parquet files with .sas7bdat extension.

    Used by e2e tests to read synthetic fixtures that are parquet files
    with .sas7bdat extension (since pyreadstat cannot write SAS files).
    """

    def _patched_scan_readstat(
        path: str,
        schema_overrides: dict[str, Any] | None = None,
        preserve_order: bool = False,
    ) -> pl.LazyFrame:
        """Read parquet file instead of SAS file."""
        return pl.read_parquet(path).lazy()

    with patch(
        "pyaggregate.io.sas_reader.scan_readstat",
        side_effect=_patched_scan_readstat,
    ):
        yield
