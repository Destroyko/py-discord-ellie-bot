"""Ellie Discord moderation bot entry point."""

from __future__ import annotations

import asyncio
import logging
import sys

import discord
from discord.ext import commands

from core.config_loader import AppConfig, load_config
from core.exceptions import ConfigError
from core.logger import setup_logging
from core.startup_checks import run_startup_checks
from database.database import Database
from modules.channel_mutes.commands import setup_channel_mutes_cog
from modules.media_cleanup import setup_media_cleanup_cog
from modules.media_cleanup.config import MediaCleanupConfig, load_media_cleanup_config
from modules.mention_gif import setup_mention_gif_cog
from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.scheduler import MuteScheduler
from modules.channel_mutes.service import ChannelMuteService

logger = logging.getLogger("ellie_bot")


class EllieBot(commands.Bot):
    """Discord bot bound to a single configured guild."""

    def __init__(
        self,
        config: AppConfig,
        database: Database,
        media_cleanup_config: MediaCleanupConfig,
    ) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = False
        super().__init__(command_prefix=config.prefix, intents=intents)
        self.app_config = config
        self.database = database
        self.media_cleanup_config = media_cleanup_config
        self.mute_repository = ChannelMuteRepository(database)
        self.mute_service = ChannelMuteService(self, config, self.mute_repository)
        self.mute_scheduler = MuteScheduler(self.mute_service, self.mute_repository)
        self._scheduler_wired = False
        self._mutes_restored = False
        self._startup_checks_done = False

    def _wire_scheduler(self) -> None:
        if self._scheduler_wired:
            return

        async def on_scheduled(mute_id: int, expire_at) -> None:
            await self.mute_scheduler.schedule(mute_id, expire_at)

        async def on_cancelled(mute_id: int) -> None:
            await self.mute_scheduler.cancel(mute_id)

        self.mute_service.set_scheduler_hooks(on_scheduled, on_cancelled)
        self._scheduler_wired = True

    async def setup_hook(self) -> None:
        """Register cogs and sync guild slash commands."""
        self._wire_scheduler()
        await setup_channel_mutes_cog(
            self,
            self.app_config,
            self.mute_service,
            self.mute_repository,
        )
        await setup_mention_gif_cog(self, self.app_config, self.database)
        await setup_media_cleanup_cog(
            self,
            self.app_config,
            self.media_cleanup_config,
        )

        guild = discord.Object(id=self.app_config.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info(
            "Synced %s guild command(s) to guild_id=%s",
            len(synced),
            self.app_config.guild_id,
        )

    async def on_ready(self) -> None:
        """Log readiness, validate guild, restore mute timers."""
        if self.user:
            logger.info("Logged in as %s (%s)", self.user, self.user.id)

        guild = self.get_guild(self.app_config.guild_id)
        if guild is None:
            try:
                guild = await self.fetch_guild(self.app_config.guild_id)
            except discord.HTTPException:
                logger.error(
                    "Configured guild_id=%s not found. Invite the bot or fix config.",
                    self.app_config.guild_id,
                )
                return

        logger.info("Connected to target guild: %s (%s)", guild.name, guild.id)

        if not self._mutes_restored:
            await self.mute_scheduler.restore_all(self.app_config.guild_id)
            self._mutes_restored = True
            logger.info("Mute scheduler restored for guild %s", guild.id)

        if not self._startup_checks_done:
            await run_startup_checks(guild, self.app_config, self.media_cleanup_config)
            self._startup_checks_done = True


async def main() -> None:
    """Load config, initialize database, and run the bot."""
    try:
        config = load_config()
        media_cleanup_config = load_media_cleanup_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config.log_level)
    logger.info("Starting Ellie bot for guild_id=%s", config.guild_id)

    database = Database(config.database_path)
    database.init_db()
    logger.info("Database initialized at %s", config.database_path)

    bot = EllieBot(config, database, media_cleanup_config)

    try:
        await bot.start(config.discord_token)
    finally:
        database.close()


if __name__ == "__main__":
    asyncio.run(main())
