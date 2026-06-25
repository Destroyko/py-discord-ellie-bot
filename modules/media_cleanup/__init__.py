"""Automatic text cleanup in media-only Discord channels."""

from __future__ import annotations

import logging

from discord.ext import commands

from core.config_loader import AppConfig
from modules.media_cleanup.cog import MediaCleanupCog
from modules.media_cleanup.config import MediaCleanupConfig, load_media_cleanup_config
from modules.media_cleanup.service import MediaCleanupService

logger = logging.getLogger("ellie_bot")


async def setup_media_cleanup_cog(
    bot: commands.Bot,
    app_config: AppConfig,
    cleanup_config: MediaCleanupConfig | None = None,
) -> MediaCleanupCog | None:
    """Register the media cleanup background task when enabled in config."""
    config = cleanup_config if cleanup_config is not None else load_media_cleanup_config()

    if not config.enabled:
        logger.info("Media channel cleanup is disabled in config")
        return None

    service = MediaCleanupService(config)
    cog = MediaCleanupCog(bot, app_config, config, service)
    await bot.add_cog(cog)
    logger.info(
        "Media channel cleanup enabled for %s channel(s)",
        len(config.channel_ids),
    )
    return cog
