"""Persistence for channel mutes (no discord.py imports)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from database.database import Database
from database.models import ChannelMute


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _row_to_mute(row: Any) -> ChannelMute:
    snapshot_raw = row["overwrite_snapshot"]
    snapshot: dict[str, Any] | None = None
    if snapshot_raw:
        snapshot = json.loads(snapshot_raw)
    return ChannelMute(
        id=row["id"],
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        user_id=row["user_id"],
        moderator_id=row["moderator_id"],
        reason=row["reason"],
        created_at=_from_iso(row["created_at"]),
        expire_at=_from_iso(row["expire_at"]),
        overwrite_snapshot=snapshot,
    )


class ChannelMuteRepository:
    """CRUD operations for channel_mutes table."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def insert(self, mute: ChannelMute) -> ChannelMute:
        """Insert a new mute record and return it with id."""
        conn = self._db.connect()
        snapshot_json = (
            json.dumps(mute.overwrite_snapshot) if mute.overwrite_snapshot is not None else None
        )
        cursor = conn.execute(
            """
            INSERT INTO channel_mutes (
                guild_id, channel_id, user_id, moderator_id,
                reason, created_at, expire_at, overwrite_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mute.guild_id,
                mute.channel_id,
                mute.user_id,
                mute.moderator_id,
                mute.reason,
                _to_iso(mute.created_at),
                _to_iso(mute.expire_at),
                snapshot_json,
            ),
        )
        conn.commit()
        mute_id = int(cursor.lastrowid)
        result = self.get_by_id(mute_id)
        assert result is not None
        return result

    def update_extend(
        self,
        mute_id: int,
        *,
        expire_at: datetime,
        moderator_id: int,
        reason: str | None,
        created_at: datetime,
    ) -> ChannelMute | None:
        """Update mute on extension (snapshot unchanged)."""
        conn = self._db.connect()
        conn.execute(
            """
            UPDATE channel_mutes
            SET expire_at = ?, moderator_id = ?, reason = ?, created_at = ?
            WHERE id = ?
            """,
            (_to_iso(expire_at), moderator_id, reason, _to_iso(created_at), mute_id),
        )
        conn.commit()
        return self.get_by_id(mute_id)

    def delete(self, mute_id: int) -> None:
        """Remove a mute record by primary key."""
        conn = self._db.connect()
        conn.execute("DELETE FROM channel_mutes WHERE id = ?", (mute_id,))
        conn.commit()

    def delete_by_keys(self, guild_id: int, channel_id: int, user_id: int) -> None:
        """Remove a mute by unique business key."""
        conn = self._db.connect()
        conn.execute(
            """
            DELETE FROM channel_mutes
            WHERE guild_id = ? AND channel_id = ? AND user_id = ?
            """,
            (guild_id, channel_id, user_id),
        )
        conn.commit()

    def get_by_id(self, mute_id: int) -> ChannelMute | None:
        """Fetch mute by id."""
        conn = self._db.connect()
        row = conn.execute(
            "SELECT * FROM channel_mutes WHERE id = ?", (mute_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_mute(row)

    def get_by_keys(
        self, guild_id: int, channel_id: int, user_id: int
    ) -> ChannelMute | None:
        """Fetch mute by guild/channel/user unique key."""
        conn = self._db.connect()
        row = conn.execute(
            """
            SELECT * FROM channel_mutes
            WHERE guild_id = ? AND channel_id = ? AND user_id = ?
            """,
            (guild_id, channel_id, user_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_mute(row)

    def list_active_for_user(self, guild_id: int, user_id: int) -> list[ChannelMute]:
        """List non-expired mutes for a user (by DB expire_at)."""
        now = _to_iso(_utc_now())
        conn = self._db.connect()
        rows = conn.execute(
            """
            SELECT * FROM channel_mutes
            WHERE guild_id = ? AND user_id = ? AND expire_at > ?
            ORDER BY expire_at ASC
            """,
            (guild_id, user_id, now),
        ).fetchall()
        return [_row_to_mute(row) for row in rows]

    def list_all_active(self, guild_id: int) -> list[ChannelMute]:
        """List all non-expired mutes on the guild."""
        now = _to_iso(_utc_now())
        conn = self._db.connect()
        rows = conn.execute(
            """
            SELECT * FROM channel_mutes
            WHERE guild_id = ? AND expire_at > ?
            ORDER BY expire_at ASC
            """,
            (guild_id, now),
        ).fetchall()
        return [_row_to_mute(row) for row in rows]

    def list_expired(self, guild_id: int) -> list[ChannelMute]:
        """List mutes whose expire_at is in the past."""
        now = _to_iso(_utc_now())
        conn = self._db.connect()
        rows = conn.execute(
            """
            SELECT * FROM channel_mutes
            WHERE guild_id = ? AND expire_at <= ?
            """,
            (guild_id, now),
        ).fetchall()
        return [_row_to_mute(row) for row in rows]
