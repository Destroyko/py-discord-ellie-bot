"""Persist mention-GIF cooldown timestamps in SQLite."""

from __future__ import annotations

from datetime import datetime, timezone

from database.database import Database

_COOLDOWN_KEY_PREFIX = "mention_gif:last_sent:"


def _cooldown_key(guild_id: int) -> str:
    return f"{_COOLDOWN_KEY_PREFIX}{guild_id}"


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class MentionGifCooldownRepository:
    """Guild-wide last-sent timestamp for mention GIF replies."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def get_last_sent_at(self, guild_id: int) -> datetime | None:
        """Return when the bot last sent a mention GIF in this guild."""
        conn = self._db.connect()
        row = conn.execute(
            "SELECT value FROM bot_meta WHERE key = ?",
            (_cooldown_key(guild_id),),
        ).fetchone()
        if row is None:
            return None
        return _from_iso(str(row["value"]))

    def set_last_sent_at(self, guild_id: int, sent_at: datetime) -> None:
        """Record a successful mention GIF reply."""
        conn = self._db.connect()
        conn.execute(
            """
            INSERT INTO bot_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (_cooldown_key(guild_id), _to_iso(sent_at)),
        )
        conn.commit()
