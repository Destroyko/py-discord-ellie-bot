"""Direct messages to muted users."""

from __future__ import annotations

import logging
from datetime import datetime

import discord

logger = logging.getLogger("ellie_bot")


def _format_expire(expire_at: datetime) -> str:
    return expire_at.strftime("%Y-%m-%d %H:%M UTC")


class DmNotifier:
    """Send DM notifications; failures are logged, not raised."""

    async def send_mute_issued(
        self,
        target: discord.Member,
        *,
        guild_name: str,
        channel_name: str,
        expire_at: datetime,
        duration_text: str | None,
        reason: str | None = None,
    ) -> None:
        """Notify user of new or extended mute."""
        reason_text = reason if reason else "не указана"
        duration_display = duration_text or f"до {_format_expire(expire_at)}"
        text = (
            f"Сервер: {guild_name}\n"
            f"Канал: #{channel_name}\n"
            f"Срок: {duration_display}\n"
            f"Причина: {reason_text}"
        )
        await self._safe_send(target, text)

    async def send_unmute(
        self,
        target: discord.Member,
        *,
        guild_name: str,
        channel_name: str,
    ) -> None:
        """Notify user that channel mute was removed."""
        text = (
            f"Сервер: {guild_name}\n"
            f"Канал: #{channel_name}\n"
            "С вас снято ограничение на отправку сообщений в этом канале."
        )
        await self._safe_send(target, text)

    async def _safe_send(self, target: discord.Member, content: str) -> None:
        try:
            await target.send(content)
        except discord.Forbidden:
            logger.warning("Cannot DM user %s (DM closed or blocked)", target.id)
        except discord.HTTPException:
            logger.exception("Failed to DM user %s", target.id)
