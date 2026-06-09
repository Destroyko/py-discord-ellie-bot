"""SQLite database access."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database.migrations import (
    ALL_MIGRATIONS,
    CHANNEL_MUTES_REBUILD_BELOW_VERSION,
    CREATE_SCHEMA_VERSION,
    DROP_CHANNEL_MUTES_TABLE,
    SCHEMA_VERSION,
)


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
        """
        Apply migrations and set schema version.

        Fresh databases get all tables created. When upgrading from an older
        schema version, the channel_mutes table is rebuilt cleanly (data reset)
        because the mute scope feature changes its unique key.
        """
        conn = self.connect()
        conn.execute(CREATE_SCHEMA_VERSION)
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        current_version = row["version"] if row is not None else None

        if (
            current_version is not None
            and current_version < CHANNEL_MUTES_REBUILD_BELOW_VERSION
        ):
            conn.execute(DROP_CHANNEL_MUTES_TABLE)

        for sql in ALL_MIGRATIONS:
            conn.execute(sql)

        if row is None:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
        elif current_version is not None and current_version < SCHEMA_VERSION:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        conn.commit()
