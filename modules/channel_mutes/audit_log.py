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
        previous_duration_text: str | None = None,
        previous_expire_at: datetime | None = None,
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
        channel_display = f"<#{ch_id}>" if ch_id else f"**#{ch_name}**"

        uid = target_user_id or (target.id if target else 0)
        user_mention = f"<@{uid}>"

        mod_id = moderator_id or (moderator.id if moderator else 0)
        if action == AuditAction.AUTO_UNMUTED:
            actor = guild.me.display_name if guild.me else "Бот"
            line = (
                f"**{actor}** снял запрет пользователю {user_mention} "
                f"общаться в чате {channel_display} (истёк срок)"
            )
        else:
            mod_mention = f"<@{mod_id}>"
            if action == AuditAction.MUTED:
                verb = "запретил"
            elif action == AuditAction.EXTENDED:
                verb = "обновил запрет"
            else:
                verb = "снял запрет"
            line = (
                f"{mod_mention} **{verb}** пользователю {user_mention} "
                f"общаться в чате {channel_display}"
            )

        extra_parts: list[str] = []
        if action == AuditAction.EXTENDED:
            if previous_duration_text:
                extra_parts.append(f"Было: {previous_duration_text}")
            elif previous_expire_at:
                extra_parts.append(f"Было: до {previous_expire_at.strftime('%Y-%m-%d %H:%M UTC')}")
            if duration_text:
                extra_parts.append(f"Стало: {duration_text}")
            elif expire_at:
                extra_parts.append(f"Стало: до {expire_at.strftime('%Y-%m-%d %H:%M UTC')}")
        elif action == AuditAction.MUTED:
            if duration_text:
                extra_parts.append(f"Срок: {duration_text}")
            elif expire_at:
                extra_parts.append(f"Срок: до {expire_at.strftime('%Y-%m-%d %H:%M UTC')}")
        if reason and action in (AuditAction.MUTED, AuditAction.EXTENDED):
            extra_parts.append(f"Причина: {reason}")
        if action == AuditAction.EXTENDED:
            extra_parts.append("Обновлено")

        ids_lines = [
            f"Пользователь: {uid}",
            f"Чат: {ch_id}",
        ]
        if action != AuditAction.AUTO_UNMUTED:
            ids_lines.append(f"Модератор: {mod_id}")
        body = line
        if extra_parts:
            body += "\n" + "\n".join(extra_parts)
        body += "\n" + "\n".join(ids_lines)

        if action == AuditAction.MUTED:
            embed_color = discord.Color.red()
            title = "Наказание"
        elif action == AuditAction.EXTENDED:
            embed_color = discord.Color.yellow()
            title = "Обновление наказания"
        else:
            embed_color = discord.Color.green()
            title = "Снятие наказания"

        embed = discord.Embed(
            # title=title,
            description=body,
            color=embed_color,
        )

        try:
            await logs_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except discord.HTTPException:
            logger.exception("Failed to post audit log to channel %s", logs_channel.id)
