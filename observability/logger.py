"""Structured JSON logging setup for SlotPilot."""
from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGS_DIR = Path(__file__).parent.parent / "logs"
_SETUP_DONE = False


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra fields passed via the `extra=` kwarg
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__ and key not in payload:
                payload[key] = val
        return json.dumps(payload, default=str)


class _HumanFormatter(logging.Formatter):
    """Human-readable format for console output."""

    FMT = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"

    def __init__(self) -> None:
        super().__init__(self.FMT, datefmt="%H:%M:%S")


def setup_logging() -> None:
    """Configure root logger once at application startup.

    Reads LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT from environment.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _SETUP_DONE
    if _SETUP_DONE:
        return

    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    max_bytes = int(os.getenv("LOG_MAX_BYTES", "10485760"))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any default handlers that may have been added before setup
    root.handlers.clear()

    # Rotating JSON file handler
    file_handler = RotatingFileHandler(
        _LOGS_DIR / "app.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(_JsonFormatter())
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Console handler — human-readable
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_HumanFormatter())
    console_handler.setLevel(level)
    root.addHandler(console_handler)

    _SETUP_DONE = True

    logging.getLogger(__name__).info(
        "Logging initialised",
        extra={"log_level": level_name, "log_file": str(_LOGS_DIR / "app.log")},
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.  Call setup_logging() first."""
    return logging.getLogger(name)
