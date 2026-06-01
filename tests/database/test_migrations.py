"""Tests for SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from database.database import Database
from database.migrations import SCHEMA_VERSION


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "migrations.db")
    database.init_db()
    yield database
    database.close()


def test_channel_mutes_table_exists(db: Database) -> None:
    conn = db.connect()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='channel_mutes'"
    ).fetchone()
    assert row is not None


def test_unique_constraint_on_keys(db: Database) -> None:
    conn = db.connect()
    conn.execute(
        """
        INSERT INTO channel_mutes (
            guild_id, channel_id, user_id, moderator_id,
            reason, created_at, expire_at, overwrite_snapshot
        ) VALUES (1, 2, 3, 4, NULL, '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', NULL)
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO channel_mutes (
                guild_id, channel_id, user_id, moderator_id,
                reason, created_at, expire_at, overwrite_snapshot
            ) VALUES (1, 2, 3, 5, NULL, '2026-01-01T00:00:00Z', '2026-01-03T00:00:00Z', NULL)
            """
        )


def test_schema_version_set(db: Database) -> None:
    conn = db.connect()
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    assert row is not None
    assert row["version"] == SCHEMA_VERSION


def test_expire_at_index_exists(db: Database) -> None:
    conn = db.connect()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_channel_mutes_expire_at'"
    ).fetchone()
    assert row is not None
