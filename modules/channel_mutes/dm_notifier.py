"""Direct messages to muted users."""

from __future__ import annotations

import logging
from datetime import datetime

import discord

from modules.channel_mutes.mute_scope import MuteScope, scope_place_phrase

logger = logging.getLogger("ellie_bot")

SERVER_NAME = "Оплот работяг"
RULES_URL = "https://discord.com/channels/633759687845740545/634384447713705984"


def _format_expire(expire_at: datetime) -> str:
    return expire_at.strftime("%Y-%m-%d %H:%M UTC")


def _channel_link(guild_id: int, channel_id: int, channel_name: str) -> str:
    return f"[#{channel_name}](https://discord.com/channels/{guild_id}/{channel_id})"


class DmNotifier:
    """Send DM notifications; failures are logged, not raised."""

    async def send_mute_issued(
        self,
        target: discord.Member,
        *,
        guild_name: str,
        guild_id: int,
        channel_name: str,
        channel_id: int,
        expire_at: datetime,
        duration_text: str | None,
        reason: str | None = None,
        is_extended: bool = False,
        scope: MuteScope = MuteScope.CHAT_ONLY,
    ) -> None:
        """Notify user of new or extended mute."""
        reason_text = reason if reason else "не указана"
        duration_display = duration_text or f"до {_format_expire(expire_at)}"
        channel_display = _channel_link(guild_id, channel_id, channel_name)
        place = scope_place_phrase(scope, channel_display)
        action_text = "Вам обновили время запрета" if is_extended else "Вы получили запрет"
        title = "Продление наказания" if is_extended else "Наказание"
        color = discord.Color.yellow() if is_extended else discord.Color.red()

        description = (
            f'{action_text} на общение {place} '
            f'на сервере "{SERVER_NAME}" продолжительность {duration_display}\n\n'
            "**Причина**\n"
            f"{reason_text}\n\n"
            f"[Правила сервера]({RULES_URL})\n"
            "-# Для обжалования вы можете обратиться к старшим модераторам или "
            "супермодераторам, перед обращением рекомендуем ознакомиться с "
            "разделом правил сервера"
        )
        embed = discord.Embed(
            # title=title,
            description=description,
            color=color,
        )
        await self._safe_send(target, embed=embed)

    async def send_unmute(
        self,
        target: discord.Member,
        *,
        guild_name: str,
        guild_id: int,
        channel_name: str,
        channel_id: int,
        scope: MuteScope = MuteScope.CHAT_ONLY,
    ) -> None:
        """Notify user that channel mute was removed."""
        channel_display = _channel_link(guild_id, channel_id, channel_name)
        place = scope_place_phrase(scope, channel_display)
        description = (
            f'С вас снят запрет общаться {place} '
            f'на сервере "{SERVER_NAME}".\n\n'
            f"[Правила сервера]({RULES_URL})"
        )
        embed = discord.Embed(
            # title="Снятие наказания",
            description=description,
            color=discord.Color.green(),
        )
        await self._safe_send(target, embed=embed)

    async def _safe_send(
        self,
        target: discord.Member,
        *,
        embed: discord.Embed,
    ) -> None:
        try:
            await target.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            logger.warning("Cannot DM user %s (DM closed or blocked)", target.id)
        except discord.HTTPException:
            logger.exception("Failed to DM user %s", target.id)
