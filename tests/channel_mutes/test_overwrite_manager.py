"""Tests for OverwriteManager forum partial apply."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.exceptions import DiscordActionError
from modules.channel_mutes.mute_scope import MuteScope
from modules.channel_mutes.overwrite_manager import OverwriteManager
from modules.channel_mutes.permissions_bits import (
    CREATE_PUBLIC_THREADS_BIT,
    SEND_MESSAGES_IN_THREADS_BIT,
    SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS,
)
from tests.conftest import make_forum_channel, make_member, overwrite_without_deny


@pytest.fixture
def manager() -> OverwriteManager:
    return OverwriteManager()


class TestForumApplyMute:
    async def test_both_bits_applied_on_success(self, manager: OverwriteManager) -> None:
        forum = make_forum_channel()
        forum.overwrites_for = MagicMock(return_value=overwrite_without_deny())
        member = make_member(member_id=50)

        pairs = await manager.apply_mute(forum, member, MuteScope.FORUM)

        forum.set_permissions.assert_awaited_once()
        assert len(pairs) == 2

    async def test_retry_send_only_on_create_failure(
        self,
        manager: OverwriteManager,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        forum = make_forum_channel()
        forum.overwrites_for = MagicMock(return_value=overwrite_without_deny())
        member = make_member(member_id=50)
        calls = 0

        async def flaky_set_permissions(*_a: object, **_k: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise discord.HTTPException(MagicMock(), "create denied")

        forum.set_permissions = AsyncMock(side_effect=flaky_set_permissions)

        pairs = await manager.apply_mute(forum, member, MuteScope.FORUM)

        assert calls == 2
        assert pairs == [
            (SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS, SEND_MESSAGES_IN_THREADS_BIT)
        ]
        assert "create_public_threads deny failed" in caplog.text

    async def test_send_failure_raises(self, manager: OverwriteManager) -> None:
        forum = make_forum_channel()
        forum.overwrites_for = MagicMock(return_value=overwrite_without_deny())
        member = make_member(member_id=50)
        forum.set_permissions = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(), "denied")
        )

        with pytest.raises(DiscordActionError):
            await manager.apply_mute(forum, member, MuteScope.FORUM)

        assert forum.set_permissions.await_count == 2
