"""Tests for bulk unmute planning helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.models import ChannelMute
from modules.channel_mutes.mute_scope import MuteScope
from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.unmute_plan import (
    collect_unmute_records,
    notification_scope_for_channel,
    unique_channel_ids,
)
def _record(
    *,
    channel_id: int,
    scope: MuteScope,
    user_id: int = 50,
) -> ChannelMute:
    now = datetime.now(timezone.utc)
    return ChannelMute(
        id=None,
        guild_id=100,
        channel_id=channel_id,
        user_id=user_id,
        moderator_id=60,
        reason=None,
        created_at=now,
        expire_at=now + timedelta(hours=1),
        overwrite_snapshot=None,
        scope=scope,
    )


class TestCollectUnmuteRecords:
    def test_filter_by_channel_and_scope(
        self, mute_repo: ChannelMuteRepository
    ) -> None:
        mute_repo.insert(_record(channel_id=400, scope=MuteScope.CHAT_ONLY))
        mute_repo.insert(_record(channel_id=400, scope=MuteScope.THREADS_ONLY))
        mute_repo.insert(_record(channel_id=401, scope=MuteScope.CHAT_ONLY))

        chat_only = collect_unmute_records(
            mute_repo, 100, 50, channel_id=400, scope_filter=MuteScope.CHAT_ONLY
        )
        assert len(chat_only) == 1
        assert chat_only[0].scope is MuteScope.CHAT_ONLY

        in_channel = collect_unmute_records(
            mute_repo, 100, 50, channel_id=400, scope_filter=None
        )
        assert len(in_channel) == 2


class TestUniqueChannelIds:
    def test_two_scopes_same_channel_is_one(self) -> None:
        records = [
            _record(channel_id=400, scope=MuteScope.CHAT_ONLY),
            _record(channel_id=400, scope=MuteScope.THREADS_ONLY),
        ]
        assert unique_channel_ids(records) == {400}


class TestNotificationScopeForChannel:
    def test_chat_and_threads_when_both_removed(self) -> None:
        scopes = {MuteScope.CHAT_ONLY, MuteScope.THREADS_ONLY}
        assert notification_scope_for_channel(scopes) is MuteScope.CHAT_AND_THREADS

    def test_chat_only_when_single_aspect(self) -> None:
        assert (
            notification_scope_for_channel({MuteScope.CHAT_ONLY})
            is MuteScope.CHAT_ONLY
        )

    def test_combined_record(self) -> None:
        assert (
            notification_scope_for_channel({MuteScope.CHAT_AND_THREADS})
            is MuteScope.CHAT_AND_THREADS
        )

    def test_forum_keeps_forum_phrasing(self) -> None:
        assert (
            notification_scope_for_channel({MuteScope.FORUM})
            is MuteScope.FORUM
        )
