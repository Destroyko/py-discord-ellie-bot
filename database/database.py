"""SQLite database access."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database.migrations import ALL_MIGRATIONS, SCHEMA_VERSION


class Database:
    """Thin wrapper around sqlite3 for channel mutes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        """Return an open connection, creating it if needed."""
        if self._connection is None:
            self._connection = sqlite3.connect(self._path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA busy_timeout=5000")
        return self._connection

    def close(self) -> None:
        """Close the underlying connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def init_db(self) -> None:
        """Apply migrations and set schema version."""
        conn = self.connect()
        for sql in ALL_MIGRATIONS:
            conn.execute(sql)
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
        conn.commit()
