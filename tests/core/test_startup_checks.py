"""Tests for startup permission checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.config_loader import AppConfig
from core.startup_checks import collect_guild_mute_permission_issues
from modules.media_cleanup.config import MediaCleanupConfig
from tests.conftest import app_config, make_guild_me, make_text_channel


class TestCollectGuildMutePermissionIssues:
    def test_no_missing_permissions(self) -> None:
        me = make_guild_me(manage_channels=True, manage_roles=True)
        assert collect_guild_mute_permission_issues(me) == []

    def test_missing_both_guild_permissions(self) -> None:
        me = make_guild_me(manage_channels=False, manage_roles=False)
        issues = collect_guild_mute_permission_issues(me)
        assert len(issues) == 2
        assert "Управление каналами" in issues[0]
        assert "Управление ролями" in issues[1]
