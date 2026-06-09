"""Tests for mention GIF channel permissions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord

from modules.mention_gif.permissions import can_send_gif


def _perms(
    *,
    view_channel: bool = True,
    send_messages: bool = True,
    attach_files: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        view_channel=view_channel,
        send_messages=send_messages,
        attach_files=attach_files,
    )


def test_all_permissions_required() -> None:
    channel = MagicMock(spec=discord.TextChannel)
    member = MagicMock(spec=discord.Member)
    channel.permissions_for.return_value = _perms()
    assert can_send_gif(channel, member) is True


def test_missing_attach_files() -> None:
    channel = MagicMock(spec=discord.TextChannel)
    member = MagicMock(spec=discord.Member)
    channel.permissions_for.return_value = _perms(attach_files=False)
    assert can_send_gif(channel, member) is False


def test_none_member() -> None:
    channel = MagicMock(spec=discord.TextChannel)
    assert can_send_gif(channel, None) is False
