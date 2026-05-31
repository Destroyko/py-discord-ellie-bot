"""Short moderation notices for the moderator commands channel."""

from __future__ import annotations

import logging

import discord

from core.config_loader import AppConfig

logger = logging.getLogger("ellie_bot")


class ModeratorNotifier:
    """Send concise visible notices to moderator_commands_channel_id."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def send_mute_notice(
        self,
        guild: discord.Guild,
        *,
        target: discord.Member,
        channel: discord.TextChannel,
        duration_text: str,
        reason: str | None,
    ) -> None:
        """Notify moderators that a member was muted in a channel."""
        notice_channel = guild.get_channel(self._config.moderator_commands_channel_id)
        if not isinstance(notice_channel, discord.TextChannel):
            logger.error(
                "moderator_commands channel %s not found",
                self._config.moderator_commands_channel_id,
            )
            return

        reason_text = reason if reason else "не указано"
        text = (
            f"{target.mention} замючен в чате {channel.mention}\n"
            f"на {duration_text}\n"
            "причина:\n"
            f"{reason_text}"
        )

        try:
            await notice_channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to post moderator notice to channel %s",
                notice_channel.id,
            )
