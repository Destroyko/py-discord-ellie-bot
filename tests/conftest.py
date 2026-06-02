"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from core.config_loader import AppConfig
from database.database import Database
from database.models import ChannelMute
from modules.channel_mutes.repository import ChannelMuteRepository


@pytest.fixture
def app_config() -> AppConfig:
    """Minimal AppConfig for channel/permission tests."""
    return AppConfig(
        discord_token="test-token",
        guild_id=100,
        database_path=Path(":memory:"),
        log_level="INFO",
        prefix="!",
        moderator_commands_channel_id=200,
        bot_logs_channel_id=300,
        moderator_role_ids=(10, 20, 30),
    )


@pytest.fixture
def memory_db(tmp_path: Path) -> Database:
    """SQLite database with migrations applied."""
    db = Database(tmp_path / "test.db")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def mute_repo(memory_db: Database) -> ChannelMuteRepository:
    return ChannelMuteRepository(memory_db)


def make_role(role_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=role_id)


class FakeRole:
    """Comparable role stand-in for hierarchy checks."""

    def __init__(self, position: int) -> None:
        self.position = position

    def __le__(self, other: object) -> bool:
        if not isinstance(other, FakeRole):
            return NotImplemented
        return self.position <= other.position


def make_member(
    *,
    member_id: int = 1,
    guild_id: int = 100,
    owner_id: int = 999,
    is_bot: bool = False,
    administrator: bool = False,
    role_ids: tuple[int, ...] = (),
    top_role_position: int = 5,
) -> MagicMock:
    """Lightweight discord.Member stand-in."""
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.bot = is_bot
    member.roles = [make_role(rid) for rid in role_ids]
    member.guild_permissions = SimpleNamespace(administrator=administrator)
    member.guild = MagicMock(spec=discord.Guild)
    member.guild.id = guild_id
    member.guild.owner_id = owner_id
    member.top_role = FakeRole(top_role_position)
    return member


def make_guild_me(
    *,
    manage_channels: bool = True,
    manage_roles: bool = True,
    top_role_position: int = 10,
) -> MagicMock:
    me = MagicMock(spec=discord.Member)
    me.guild_permissions = SimpleNamespace(
        manage_channels=manage_channels,
        manage_roles=manage_roles,
    )
    me.top_role = FakeRole(top_role_position)
    return me


def make_text_channel(
    *,
    channel_id: int = 400,
    guild_id: int = 100,
) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = "general"
    channel.guild = MagicMock(spec=discord.Guild)
    channel.guild.id = guild_id
    return channel


def sample_mute(
    *,
    mute_id: int | None = 1,
    guild_id: int = 100,
    channel_id: int = 400,
    user_id: int = 50,
    moderator_id: int = 60,
    snapshot: dict[str, Any] | None = None,
    expire_in: timedelta = timedelta(hours=2),
) -> ChannelMute:
    now = datetime.now(timezone.utc)
    return ChannelMute(
        id=mute_id,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        moderator_id=moderator_id,
        reason="test",
        created_at=now,
        expire_at=now + expire_in,
        overwrite_snapshot=snapshot,
    )


def overwrite_with_deny() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite.from_pair(
        discord.Permissions.none(),
        discord.Permissions(discord.Permissions.send_messages.flag),
    )


def overwrite_without_deny() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite.from_pair(
        discord.Permissions.none(),
        discord.Permissions.none(),
    )
