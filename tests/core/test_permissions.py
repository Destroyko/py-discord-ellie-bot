"""Tests for moderation permission policy."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.config_loader import AppConfig
from core.permissions import (
    best_role_rank,
    bot_can_moderate_member,
    can_moderate,
    can_mute_target,
)
from tests.conftest import app_config, make_guild_me, make_member


@pytest.fixture
def config(app_config: AppConfig) -> AppConfig:
    return app_config


class TestBestRoleRank:
    def test_returns_highest_rank(self, config: AppConfig) -> None:
        member = make_member(role_ids=(30, 10))
        assert best_role_rank(member, config.moderator_role_ids) == 0

    def test_no_configured_roles(self, config: AppConfig) -> None:
        member = make_member(role_ids=(99,))
        assert best_role_rank(member, config.moderator_role_ids) is None


class TestCanModerate:
    def test_administrator(self, config: AppConfig) -> None:
        member = make_member(administrator=True)
        assert can_moderate(member, config) is True

    def test_moderator_role(self, config: AppConfig) -> None:
        member = make_member(role_ids=(20,))
        assert can_moderate(member, config) is True

    def test_no_rights(self, config: AppConfig) -> None:
        member = make_member()
        assert can_moderate(member, config) is False


class TestCanMuteTarget:
    def test_self_denied(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, role_ids=(10,))
        ok, msg = can_mute_target(mod, mod, config)
        assert ok is False and msg is not None

    def test_bot_denied(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, role_ids=(10,))
        target = make_member(member_id=2, is_bot=True)
        ok, _ = can_mute_target(mod, target, config)
        assert ok is False

    def test_owner_denied(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, role_ids=(10,))
        target = make_member(member_id=999, owner_id=999)
        ok, _ = can_mute_target(mod, target, config)
        assert ok is False

    def test_target_admin_denied(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, role_ids=(10,))
        target = make_member(member_id=2, administrator=True)
        ok, _ = can_mute_target(mod, target, config)
        assert ok is False

    def test_mod_admin_bypasses_hierarchy(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, administrator=True)
        target = make_member(member_id=2, role_ids=(10,))
        ok, msg = can_mute_target(mod, target, config)
        assert ok is True and msg is None

    def test_target_without_mod_role_allowed(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, role_ids=(10,))
        target = make_member(member_id=2)
        ok, msg = can_mute_target(mod, target, config)
        assert ok is True and msg is None

    def test_mod_senior_to_target(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, role_ids=(10,))
        target = make_member(member_id=2, role_ids=(30,))
        ok, _ = can_mute_target(mod, target, config)
        assert ok is True

    def test_mod_equal_or_junior_denied(self, config: AppConfig) -> None:
        mod = make_member(member_id=1, role_ids=(30,))
        target = make_member(member_id=2, role_ids=(10,))
        ok, _ = can_mute_target(mod, target, config)
        assert ok is False

    def test_mod_without_configured_role_denied(self, config: AppConfig) -> None:
        mod = make_member(member_id=1)
        target = make_member(member_id=2)
        ok, _ = can_mute_target(mod, target, config)
        assert ok is False


class TestBotCanModerateMember:
    def test_ok(self) -> None:
        guild = MagicMock()
        guild.me = make_guild_me(manage_channels=True, top_role_position=10)
        target = make_member(member_id=2, top_role_position=5)
        ok, msg = bot_can_moderate_member(guild, target)
        assert ok is True and msg is None

    def test_no_guild_permissions(self) -> None:
        guild = MagicMock()
        guild.me = make_guild_me(manage_channels=False, manage_roles=False)
        target = make_member(member_id=2)
        ok, msg = bot_can_moderate_member(guild, target)
        assert ok is False
        assert msg == (
            "Не могу выдать наказание: у бота нет серверных прав: "
            "«Управление каналами», «Управление ролями»."
        )

    def test_no_channel_permissions(self) -> None:
        guild = MagicMock()
        guild.me = make_guild_me()
        target = make_member(member_id=2)
        channel = MagicMock()
        channel.name = "general"
        channel.permissions_for = MagicMock(
            return_value=SimpleNamespace(
                manage_channels=False,
                manage_roles=True,
            )
        )
        ok, msg = bot_can_moderate_member(guild, target, channel)
        assert ok is False
        assert msg == (
            "Не могу выдать наказание: у бота нет прав в канале #general: "
            "«Управление каналами»."
        )

    def test_role_too_low(self) -> None:
        guild = MagicMock()
        guild.me = make_guild_me(top_role_position=3)
        target = make_member(member_id=2, top_role_position=5)
        ok, msg = bot_can_moderate_member(guild, target)
        assert ok is False and msg is not None
