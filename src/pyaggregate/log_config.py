# pattern: Imperative Shell
"""Structured JSON logging configuration."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Formatter that produces JSON-lines output with structured fields.

    Each log record is formatted as a single JSON object with standard fields
    (timestamp, level, logger, message) plus any extra fields from the record.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a single JSON line.

        Args:
            record: LogRecord to format

        Returns:
            String containing a single JSON object (one line)
        """
        # Standard fields
        log_dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge extra fields from record.__dict__
        # Exclude internal logging fields
        exclude_keys = {
            "name",
            "msg",
            "args",
            "created",
            "msecs",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "getMessage",
        }

        for key, value in record.__dict__.items():
            if key not in exclude_keys and not key.startswith("_"):
                log_dict[key] = value

        return json.dumps(log_dict)


def configure_logging(log_dir: Path | None, level: int = logging.INFO) -> None:
    """Configure structured JSON logging for pyaggregate.

    Sets up a root logger for the 'pyaggregate' namespace with:
    - StreamHandler to stderr with JsonFormatter
    - FileHandler to log_dir/pyaggregate-YYYY-MM-DD.log (if log_dir provided)

    Should be called once at CLI entry point before any commands run.

    Args:
        log_dir: Directory for log files. If None, only stderr handler is created.
        level: Logging level (default: INFO)
    """
    root_logger = logging.getLogger("pyaggregate")
    root_logger.setLevel(level)

    # Remove any existing handlers to avoid duplication
    root_logger.handlers.clear()

    # Create stderr handler
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(stderr_handler)

    # Create file handler if log_dir provided
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)

        # Log file named with current date: pyaggregate-YYYY-MM-DD.log
        today = datetime.now(UTC).date().isoformat()
        log_file = log_dir / f"pyaggregate-{today}.log"

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)
