"""Tests for mention GIF on_message listener."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from core.config_loader import AppConfig
from database.database import Database
from modules.mention_gif.cog import MentionGifCog
from modules.mention_gif.cooldown import GuildCooldownTracker
from modules.mention_gif.cooldown_repository import MentionGifCooldownRepository
from modules.mention_gif.gif_pool import GifPool
from tests.conftest import app_config, make_text_channel


@pytest.fixture
def mention_cog(tmp_path: Path, app_config: AppConfig) -> MentionGifCog:
    gif_dir = tmp_path / "gifs"
    gif_dir.mkdir()
    (gif_dir / "react.gif").write_bytes(b"gif")

    db = Database(tmp_path / "cog.db")
    db.init_db()
    tracker = GuildCooldownTracker(
        MentionGifCooldownRepository(db),
        app_config.mention_gif_cooldown_seconds,
    )

    bot = MagicMock(spec=commands.Bot)
    bot.user = MagicMock()
    bot.user.id = 999
    bot.process_commands = AsyncMock()

    config = replace(app_config, mention_gifs_dir=gif_dir)

    cog = MentionGifCog(bot, config, GifPool(gif_dir), tracker)
    yield cog
    db.close()


def _message(
    *,
    guild_id: int,
    channel: MagicMock,
    author_bot: bool = False,
    mentions_bot: bool = True,
    bot_user: MagicMock,
) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.me = MagicMock(spec=discord.Member)
    guild.me.guild_permissions = MagicMock()

    author = MagicMock()
    author.bot = author_bot

    message = MagicMock(spec=discord.Message)
    message.author = author
    message.guild = guild
    message.channel = channel
    message.mentions = [bot_user] if mentions_bot else []
    message.reply = AsyncMock()
    return message


class TestMentionGifCog:
    async def test_replies_when_mentioned(
        self, mention_cog: MentionGifCog, app_config: AppConfig
    ) -> None:
        channel = make_text_channel()
        channel.permissions_for = MagicMock(
            return_value=MagicMock(
                view_channel=True, send_messages=True, attach_files=True
            )
        )
        msg = _message(
            guild_id=app_config.guild_id,
            channel=channel,
            bot_user=mention_cog.bot.user,
        )

        await mention_cog.on_message(msg)

        msg.reply.assert_awaited_once()
        mention_cog.bot.process_commands.assert_awaited_once_with(msg)

    async def test_silent_on_cooldown(
        self, mention_cog: MentionGifCog, app_config: AppConfig
    ) -> None:
        mention_cog._cooldown.mark_sent(app_config.guild_id)
        channel = make_text_channel()
        channel.permissions_for = MagicMock(
            return_value=MagicMock(
                view_channel=True, send_messages=True, attach_files=True
            )
        )
        msg = _message(
            guild_id=app_config.guild_id,
            channel=channel,
            bot_user=mention_cog.bot.user,
        )

        await mention_cog.on_message(msg)

        msg.reply.assert_not_awaited()

    async def test_ignores_without_mention(
        self, mention_cog: MentionGifCog, app_config: AppConfig
    ) -> None:
        channel = make_text_channel()
        msg = _message(
            guild_id=app_config.guild_id,
            channel=channel,
            mentions_bot=False,
            bot_user=mention_cog.bot.user,
        )

        await mention_cog.on_message(msg)

        msg.reply.assert_not_awaited()
