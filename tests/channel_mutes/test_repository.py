"""Tests for channel mute repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database.database import Database
from database.models import ChannelMute
from modules.channel_mutes.mute_scope import MuteScope
from modules.channel_mutes.repository import (
    ChannelMuteRepository,
    _from_iso,
    _row_to_mute,
    _to_iso,
)
from tests.conftest import sample_mute


class TestIsoHelpers:
    def test_round_trip_utc(self) -> None:
        dt = datetime(2026, 6, 1, 15, 30, tzinfo=timezone.utc)
        assert _from_iso(_to_iso(dt)) == dt

    def test_naive_normalized_to_utc(self) -> None:
        naive = datetime(2026, 6, 1, 12, 0)
        iso = _to_iso(naive)
        parsed = _from_iso(iso)
        assert parsed.tzinfo == timezone.utc


class TestRowToMute:
    def test_with_snapshot_json(self) -> None:
        row = {
            "id": 1,
            "guild_id": 100,
            "channel_id": 200,
            "user_id": 50,
            "moderator_id": 60,
            "reason": "spam",
            "created_at": "2026-06-01T10:00:00Z",
            "expire_at": "2026-06-01T12:00:00Z",
            "overwrite_snapshot": '{"send_messages": true}',
            "scope": "threads_only",
        }
        mute = _row_to_mute(row)
        assert mute.id == 1
        assert mute.overwrite_snapshot == {"send_messages": True}
        assert mute.scope is MuteScope.THREADS_ONLY

    def test_null_snapshot(self) -> None:
        row = {
            "id": 2,
            "guild_id": 100,
            "channel_id": 200,
            "user_id": 51,
            "moderator_id": 60,
            "reason": None,
            "created_at": "2026-06-01T10:00:00Z",
            "expire_at": "2026-06-01T12:00:00Z",
            "overwrite_snapshot": None,
            "scope": "chat_only",
        }
        assert _row_to_mute(row).overwrite_snapshot is None


class TestChannelMuteRepository:
    @pytest.fixture
    def repo(self, memory_db: Database) -> ChannelMuteRepository:
        return ChannelMuteRepository(memory_db)

    def test_insert_and_get_by_keys(self, repo: ChannelMuteRepository) -> None:
        mute = sample_mute(mute_id=None, snapshot={"send_messages": None})
        saved = repo.insert(mute)
        assert saved.id is not None
        found = repo.get_by_keys(100, 400, 50, MuteScope.CHAT_ONLY)
        assert found is not None
        assert found.id == saved.id
        assert found.overwrite_snapshot == {"send_messages": None}

    def test_update_extend_preserves_snapshot(self, repo: ChannelMuteRepository) -> None:
        snapshot = {"send_messages": False}
        saved = repo.insert(sample_mute(mute_id=None, snapshot=snapshot))
        assert saved.id is not None
        new_expire = saved.expire_at + timedelta(hours=5)
        new_created = datetime.now(timezone.utc)
        updated = repo.update_extend(
            saved.id,
            expire_at=new_expire,
            moderator_id=99,
            reason="extended",
            created_at=new_created,
        )
        assert updated is not None
        assert updated.expire_at == new_expire
        assert updated.moderator_id == 99
        assert updated.reason == "extended"
        assert updated.overwrite_snapshot == snapshot

    def test_delete(self, repo: ChannelMuteRepository) -> None:
        saved = repo.insert(sample_mute(mute_id=None))
        assert saved.id is not None
        repo.delete(saved.id)
        assert repo.get_by_id(saved.id) is None

    def test_list_active_and_expired(self, repo: ChannelMuteRepository) -> None:
        now = datetime.now(timezone.utc)
        active = ChannelMute(
            id=None,
            guild_id=100,
            channel_id=401,
            user_id=51,
            moderator_id=60,
            reason=None,
            created_at=now,
            expire_at=now + timedelta(hours=2),
            overwrite_snapshot=None,
            scope=MuteScope.CHAT_ONLY,
        )
        expired = ChannelMute(
            id=None,
            guild_id=100,
            channel_id=402,
            user_id=52,
            moderator_id=60,
            reason=None,
            created_at=now - timedelta(hours=3),
            expire_at=now - timedelta(hours=1),
            overwrite_snapshot=None,
            scope=MuteScope.CHAT_ONLY,
        )
        repo.insert(active)
        repo.insert(expired)
        active_list = repo.list_active_for_user(100, 51)
        assert len(active_list) == 1
        assert active_list[0].channel_id == 401
        expired_list = repo.list_expired(100)
        assert any(m.channel_id == 402 for m in expired_list)
