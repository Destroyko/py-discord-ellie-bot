"""Post moderation actions to the bot logs channel."""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum

import discord

from core.config_loader import AppConfig

logger = logging.getLogger("ellie_bot")


class AuditAction(Enum):
    """Types of audit log entries."""

    MUTED = "muted"
    EXTENDED = "extended"
    UNMUTED = "unmuted"
    AUTO_UNMUTED = "auto_unmuted"


class AuditLog:
    """Send formatted messages to bot_logs_channel_id."""

    def __init__(self, bot: discord.Client, config: AppConfig) -> None:
        self._bot = bot
        self._config = config

    async def log_action(
        self,
        action: AuditAction,
        *,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel | None,
        target: discord.Member | discord.User | None,
        moderator: discord.Member | None = None,
        expire_at: datetime | None = None,
        duration_text: str | None = None,
        reason: str | None = None,
        target_user_id: int | None = None,
        channel_id: int | None = None,
        moderator_id: int | None = None,
    ) -> None:
        """Post an audit entry; failures go to file log only."""
        logs_channel = guild.get_channel(self._config.bot_logs_channel_id)
        if not isinstance(logs_channel, discord.TextChannel):
            logger.error("bot_logs channel %s not found", self._config.bot_logs_channel_id)
            return

        ch = channel
        ch_id = channel_id or (ch.id if ch else 0)
        ch_name = ch.name if isinstance(ch, discord.TextChannel) else str(ch_id)

        uid = target_user_id or (target.id if target else 0)
        user_mention = f"<@{uid}>"

        mod_id = moderator_id or (moderator.id if moderator else 0)
        if action == AuditAction.AUTO_UNMUTED:
            actor = guild.me.display_name if guild.me else "Бот"
            line = (
                f"**{actor}** снял запрет пользователю {user_mention} "
                f"общаться в чате **#{ch_name}** (истёк срок)"
            )
        else:
            mod_mention = f"<@{mod_id}>"
            if action == AuditAction.MUTED:
                verb = "запретил"
            elif action == AuditAction.EXTENDED:
                verb = "продлил запрет"
            else:
                verb = "снял запрет"
            line = (
                f"{mod_mention} **{verb}** пользователю {user_mention} "
                f"общаться в чате **#{ch_name}**"
            )

        extra_parts: list[str] = []
        if action in (AuditAction.MUTED, AuditAction.EXTENDED):
            if duration_text:
                extra_parts.append(f"Срок: {duration_text}")
            elif expire_at:
                extra_parts.append(f"Срок: до {expire_at.strftime('%Y-%m-%d %H:%M UTC')}")
        if reason and action in (AuditAction.MUTED, AuditAction.EXTENDED):
            extra_parts.append(f"Причина: {reason}")
        if action == AuditAction.EXTENDED:
            extra_parts.append("Продлено")

        ids_line = (
            f"IDs: user={uid}, channel={ch_id}, moderator={mod_id}"
        )
        body = line
        if extra_parts:
            body += "\n" + "\n".join(extra_parts)
        body += f"\n{ids_line}"

        try:
            await logs_channel.send(
                body,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except discord.HTTPException:
            logger.exception("Failed to post audit log to channel %s", logs_channel.id)
