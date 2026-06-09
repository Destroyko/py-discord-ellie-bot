"""Random GIF reply when the bot is @mentioned."""

from __future__ import annotations

import logging

from discord.ext import commands

from core.config_loader import AppConfig
from database.database import Database
from modules.mention_gif.cog import MentionGifCog
from modules.mention_gif.cooldown import GuildCooldownTracker
from modules.mention_gif.cooldown_repository import MentionGifCooldownRepository
from modules.mention_gif.gif_pool import GifPool

logger = logging.getLogger("ellie_bot")


async def setup_mention_gif_cog(
    bot: commands.Bot,
    config: AppConfig,
    database: Database,
) -> MentionGifCog | None:
    """Register the mention GIF listener if enabled in config."""
    if not config.mention_gif_enabled:
        logger.info("Mention GIF replies are disabled in config")
        return None

    gif_pool = GifPool(config.mention_gifs_dir)
    if not gif_pool.list_gifs():
        logger.warning(
            "Mention GIF pool is empty (%s); @mention replies will be skipped",
            config.mention_gifs_dir,
        )

    cooldown_repo = MentionGifCooldownRepository(database)
    cooldown_tracker = GuildCooldownTracker(
        cooldown_repo,
        config.mention_gif_cooldown_seconds,
    )
    cog = MentionGifCog(bot, config, gif_pool, cooldown_tracker)
    await bot.add_cog(cog)
    return cog
