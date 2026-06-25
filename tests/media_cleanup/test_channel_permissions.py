"""Tests for media cleanup channel permission checks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from modules.media_cleanup.permissions import collect_media_cleanup_channel_issues
from tests.conftest import make_guild_me, make_text_channel


def _channel_perms(**kwargs: bool) -> SimpleNamespace:
    defaults = {
        "view_channel": True,
        "read_message_history": True,
        "manage_messages": True,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestMediaCleanupPermissions:
    def test_all_permissions_present(self) -> None:
        channel = make_text_channel()
        channel.permissions_for = MagicMock(return_value=_channel_perms())
        me = make_guild_me()

        assert collect_media_cleanup_channel_issues(channel, me) == []

    def test_missing_manage_messages(self) -> None:
        channel = make_text_channel()
        channel.permissions_for = MagicMock(
            return_value=_channel_perms(manage_messages=False),
        )
        me = make_guild_me()

        issues = collect_media_cleanup_channel_issues(channel, me)
        assert issues == ["Управление сообщениями"]

    def test_missing_history_and_view(self) -> None:
        channel = make_text_channel()
        channel.permissions_for = MagicMock(
            return_value=_channel_perms(
                view_channel=False,
                read_message_history=False,
            ),
        )
        me = make_guild_me()

        issues = collect_media_cleanup_channel_issues(channel, me)
        assert "Просмотр канала" in issues
        assert "Чтение истории сообщений" in issues
