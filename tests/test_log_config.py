"""Test structured logging configuration."""

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from pyaggregate.log_config import JsonFormatter, configure_logging


class TestJsonFormatter:
    """Test JSON formatter produces valid JSON with standard fields."""

    def test_formats_to_valid_json_line(self):
        """JsonFormatter.format() produces valid JSON."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="/some/path/module.py",
            lineno=42,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "test message"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.module"

    def test_includes_standard_fields(self):
        """JsonFormatter includes timestamp, level, logger, message."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="pyaggregate.core",
            level=logging.WARNING,
            pathname="/some/path/file.py",
            lineno=10,
            msg="warning message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        assert "timestamp" in parsed
        assert parsed["timestamp"]  # Not empty
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "pyaggregate.core"
        assert parsed["message"] == "warning message"

    def test_merges_extra_fields(self):
        """JsonFormatter merges extra dict fields into JSON output."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="pyaggregate.io",
            level=logging.INFO,
            pathname="/some/path/file.py",
            lineno=10,
            msg="scan started",
            args=(),
            exc_info=None,
        )
        record.scan_id = "abc123"
        record.table = "demographics"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["scan_id"] == "abc123"
        assert parsed["table"] == "demographics"

    def test_excludes_pathname_from_output(self):
        """JsonFormatter excludes pathname to prevent absolute path leakage."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="/Users/scarndp/dev/Sentinel/pyAggregate/src/pyaggregate/io/scanner.py",
            lineno=42,
            msg="test",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)

        assert "pathname" not in parsed


class TestConfigureLogging:
    """Test configure_logging sets up stderr and file handlers."""

    def test_configures_root_logger(self):
        """configure_logging configures the pyaggregate root logger."""
        configure_logging(log_dir=None, level=logging.INFO)

        logger = logging.getLogger("pyaggregate")
        assert len(logger.handlers) > 0

    def test_creates_stderr_handler_by_default(self):
        """configure_logging creates a stderr handler."""
        configure_logging(log_dir=None, level=logging.INFO)

        logger = logging.getLogger("pyaggregate")
        handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert len(handlers) > 0

    def test_creates_file_handler_when_log_dir_provided(self):
        """configure_logging creates FileHandler when log_dir is provided."""
        with TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            configure_logging(log_dir=log_dir, level=logging.INFO)

            logger = logging.getLogger("pyaggregate")
            file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
            assert len(file_handlers) > 0

            # Verify file was created with expected name
            log_files = list(log_dir.glob("pyaggregate-*.log"))
            assert len(log_files) > 0

    def test_log_file_named_with_date(self):
        """Log file is named pyaggregate-YYYY-MM-DD.log."""
        with TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            configure_logging(log_dir=log_dir, level=logging.INFO)

            log_files = list(log_dir.glob("pyaggregate-*.log"))
            assert len(log_files) == 1

            filename = log_files[0].name
            # Match pattern: pyaggregate-YYYY-MM-DD.log
            assert filename.startswith("pyaggregate-")
            assert filename.endswith(".log")

    def test_sets_log_level(self):
        """configure_logging sets the specified log level."""
        with TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            configure_logging(log_dir=log_dir, level=logging.DEBUG)

            logger = logging.getLogger("pyaggregate")
            assert logger.level == logging.DEBUG

    def test_uses_json_formatter(self):
        """configure_logging attaches JsonFormatter to handlers."""
        with TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            configure_logging(log_dir=log_dir, level=logging.INFO)

            logger = logging.getLogger("pyaggregate")
            for handler in logger.handlers:
                assert isinstance(handler.formatter, JsonFormatter)

    def test_logs_to_file_in_json_format(self):
        """Logs written to file are valid JSON lines."""
        with TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            configure_logging(log_dir=log_dir, level=logging.INFO)

            logger = logging.getLogger("pyaggregate.test")
            logger.info("test message", extra={"test_field": "value"})

            log_files = list(log_dir.glob("pyaggregate-*.log"))
            assert len(log_files) == 1

            with open(log_files[0]) as f:
                lines = f.read().strip().split("\n")
                assert len(lines) > 0
                parsed = json.loads(lines[0])
                assert parsed["message"] == "test message"
                assert parsed["test_field"] == "value"
