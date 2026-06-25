"""Background task that purges idle text in configured media channels."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from core.config_loader import AppConfig
from modules.media_cleanup.config import MediaCleanupConfig
from modules.media_cleanup.service import MediaCleanupService

logger = logging.getLogger("ellie_bot")


async def resolve_text_channel(
    guild: discord.Guild,
    channel_id: int,
) -> discord.TextChannel | None:
    """Resolve a configured cleanup target to a text channel."""
    channel = guild.get_channel(channel_id)
    if isinstance(channel, discord.TextChannel):
        return channel

    try:
        fetched = await guild.fetch_channel(channel_id)
    except discord.HTTPException:
        logger.warning(
            "Media cleanup: could not fetch channel %s in guild %s",
            channel_id,
            guild.id,
        )
        return None

    if isinstance(fetched, discord.TextChannel):
        return fetched

    logger.warning(
        "Media cleanup: channel %s is not a text channel (type=%s)",
        channel_id,
        type(fetched).__name__,
    )
    return None


class MediaCleanupCog(commands.Cog):
    """Periodic purge of text messages in media-only channels."""

    def __init__(
        self,
        bot: commands.Bot,
        app_config: AppConfig,
        cleanup_config: MediaCleanupConfig,
        service: MediaCleanupService,
    ) -> None:
        self.bot = bot
        self.app_config = app_config
        self.cleanup_config = cleanup_config
        self._service = service

    async def cog_load(self) -> None:
        self.cleanup_task.start()

    async def cog_unload(self) -> None:
        self.cleanup_task.cancel()

    @tasks.loop(minutes=5)
    async def cleanup_task(self) -> None:
        guild = self.bot.get_guild(self.app_config.guild_id)
        if guild is None:
            return

        for channel_id in self.cleanup_config.channel_ids:
            channel = await resolve_text_channel(guild, channel_id)
            if channel is None:
                continue

            try:
                await self._service.maybe_cleanup_channel(channel)
            except discord.HTTPException as exc:
                if exc.status == 429:
                    retry_after = getattr(exc, "retry_after", None)
                    logger.warning(
                        "Media cleanup rate limited while reading #%s (%s), retry_after=%s",
                        channel.name,
                        channel.id,
                        retry_after,
                    )
                else:
                    logger.warning(
                        "Media cleanup failed for #%s (%s): %s",
                        channel.name,
                        channel.id,
                        exc,
                    )
            except Exception:
                logger.exception(
                    "Unexpected media cleanup error for channel %s",
                    channel_id,
                )

    @cleanup_task.before_loop
    async def before_cleanup_task(self) -> None:
        await self.bot.wait_until_ready()
