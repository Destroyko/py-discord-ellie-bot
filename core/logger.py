"""File and console logging setup."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"


def monthly_log_path(logs_dir: Path, month: str | None = None) -> Path:
    """Path for a monthly log file, e.g. ``logs/bot-2026-06.log``."""
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    return logs_dir / f"bot-{month}.log"


class MonthlyFileHandler(logging.FileHandler):
    """Write logs to ``bot-YYYY-MM.log``, opening a new file when the month changes."""

    def __init__(self, logs_dir: Path, *, encoding: str = "utf-8") -> None:
        self._logs_dir = logs_dir
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._current_month = datetime.now().strftime("%Y-%m")
        super().__init__(
            monthly_log_path(self._logs_dir, self._current_month),
            encoding=encoding,
            mode="a",
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            month = datetime.now().strftime("%Y-%m")
            if month != self._current_month:
                if self.stream:
                    self.stream.close()
                    self.stream = None
                self._current_month = month
                self.baseFilename = str(monthly_log_path(self._logs_dir, month))
            super().emit(record)
        except Exception:
            self.handleError(record)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """
    Configure root logger with console and monthly file output.

    :returns: application logger named ``ellie_bot``.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)

    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

        file_handler = MonthlyFileHandler(LOGS_DIR, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    logger = logging.getLogger("ellie_bot")
    logger.setLevel(log_level)
    return logger
