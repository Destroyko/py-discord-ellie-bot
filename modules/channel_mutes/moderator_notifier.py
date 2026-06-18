"""Short moderation notices for the moderator commands channel."""

from __future__ import annotations

import logging

import discord

from core.channel_context import MuteChannel
from core.config_loader import AppConfig
from modules.channel_mutes.mute_scope import MuteScope, scope_place_phrase

logger = logging.getLogger("ellie_bot")


class ModeratorNotifier:
    """Send concise visible notices to moderator_commands_channel_id."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def send_mute_notice(
        self,
        guild: discord.Guild,
        *,
        moderator: discord.Member,
        target: discord.Member,
        channel: MuteChannel,
        duration_text: str,
        reason: str | None,
        previous_duration_text: str | None = None,
        is_extended: bool = False,
        scope: MuteScope = MuteScope.CHAT_ONLY,
    ) -> None:
        """Notify moderators that a member was muted or extended in a channel."""
        notice_channel = guild.get_channel(self._config.moderator_commands_channel_id)
        if not isinstance(notice_channel, discord.TextChannel):
            logger.error(
                "moderator_commands channel %s not found",
                self._config.moderator_commands_channel_id,
            )
            return

        reason_text = reason if reason else "не указано"
        place = scope_place_phrase(scope, channel.mention)
        if is_extended:
            duration_line = (
                f"с {previous_duration_text} на {duration_text}"
                if previous_duration_text
                else f"на {duration_text}"
            )
            text = (
                f"{target.mention} перемьючен {place} {duration_line}\n"
                "причина:\n"
                f"{reason_text}"
            )
        else:
            text = (
                f"{target.mention} замьючен {place}\n"
                f"на {duration_text}\n"
                "причина:\n"
                f"{reason_text}"
            )

        title = "Наказание"
        color = discord.Color.red()
        if is_extended:
            title = "Обновление наказания"
            color = discord.Color.yellow()

        embed = discord.Embed(
            # title=title,
            description=text,
            color=color,
        )
        avatar = moderator.avatar or moderator.default_avatar
        embed.set_author(name=moderator.name, icon_url=avatar.url)

        try:
            await notice_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to post moderator notice to channel %s",
                notice_channel.id,
            )

    async def send_unmute_notice(
        self,
        guild: discord.Guild,
        *,
        moderator: discord.Member,
        target: discord.Member,
        places: list[str],
    ) -> None:
        """Notify moderators that restrictions were removed (one or more places)."""
        if not places:
            return

        notice_channel = guild.get_channel(self._config.moderator_commands_channel_id)
        if not isinstance(notice_channel, discord.TextChannel):
            logger.error(
                "moderator_commands channel %s not found",
                self._config.moderator_commands_channel_id,
            )
            return

        places_text = ", ".join(places)
        text = f"Запрет снят: {target.mention}, {places_text}."
        embed = discord.Embed(description=text, color=discord.Color.green())
        avatar = moderator.avatar or moderator.default_avatar
        embed.set_author(name=moderator.name, icon_url=avatar.url)

        try:
            await notice_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to post unmute notice to channel %s",
                notice_channel.id,
            )
