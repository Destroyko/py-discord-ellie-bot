"""Reply with a random GIF when the bot is @mentioned."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core.channel_context import ChannelKind, classify_channel
from core.config_loader import AppConfig
from modules.mention_gif.cooldown import GuildCooldownTracker
from modules.mention_gif.gif_pool import GifPool
from modules.mention_gif.permissions import can_send_gif

logger = logging.getLogger("ellie_bot")


def _classify_message_channel(
    channel: discord.TextChannel | discord.Thread,
    config: AppConfig,
) -> ChannelKind:
    classify_id = channel.id
    if isinstance(channel, discord.Thread) and channel.parent_id is not None:
        classify_id = channel.parent_id
    return classify_channel(classify_id, config)


class MentionGifCog(commands.Cog):
    """Send a random GIF reply on @mention (guild-wide cooldown)."""

    def __init__(
        self,
        bot: commands.Bot,
        config: AppConfig,
        gif_pool: GifPool,
        cooldown_tracker: GuildCooldownTracker,
    ) -> None:
        self.bot = bot
        self.config = config
        self._gif_pool = gif_pool
        self._cooldown = cooldown_tracker

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.config.mention_gif_enabled:
            await self.bot.process_commands(message)
            return

        if message.author.bot or message.guild is None:
            await self.bot.process_commands(message)
            return

        if message.guild.id != self.config.guild_id:
            await self.bot.process_commands(message)
            return

        if self.bot.user is None or self.bot.user not in message.mentions:
            await self.bot.process_commands(message)
            return

        channel = message.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await self.bot.process_commands(message)
            return

        if _classify_message_channel(channel, self.config) in (
            ChannelKind.BOT_LOGS,
            ChannelKind.MOD_COMMANDS,
        ):
            await self.bot.process_commands(message)
            return

        if not self._cooldown.can_send(message.guild.id):
            await self.bot.process_commands(message)
            return

        reply_channel: discord.abc.GuildChannel = (
            channel.parent if isinstance(channel, discord.Thread) else channel
        )
        if not can_send_gif(reply_channel, message.guild.me):
            await self.bot.process_commands(message)
            return

        gif_path = self._gif_pool.pick_random()
        if gif_path is None:
            await self.bot.process_commands(message)
            return

        try:
            await message.reply(file=discord.File(gif_path))
        except discord.HTTPException as exc:
            if exc.status in (403, 50013):
                logger.debug(
                    "Mention GIF skipped: missing access in channel %s (%s)",
                    reply_channel.id,
                    exc,
                )
            else:
                logger.warning(
                    "Failed to send mention GIF in channel %s: %s",
                    reply_channel.id,
                    exc,
                )
        else:
            self._cooldown.mark_sent(message.guild.id)

        await self.bot.process_commands(message)
