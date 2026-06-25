"""Startup permission and configuration checks logged to the console."""

from __future__ import annotations

import logging

import discord

from core.config_loader import AppConfig
from modules.media_cleanup.config import MediaCleanupConfig
from modules.media_cleanup.cog import resolve_text_channel
from modules.media_cleanup.permissions import collect_media_cleanup_channel_issues

logger = logging.getLogger("ellie_bot")


def collect_guild_mute_permission_issues(member: discord.Member) -> list[str]:
    """Guild-level permissions required by the channel mutes module."""
    missing: list[str] = []
    perms = member.guild_permissions

    if not perms.manage_channels:
        missing.append("право сервера «Управление каналами»")
    if not perms.manage_roles:
        missing.append("право сервера «Управление ролями»")

    return missing


async def run_startup_checks(
    guild: discord.Guild,
    app_config: AppConfig,
    media_cleanup_config: MediaCleanupConfig,
) -> None:
    """
    Verify bot permissions for enabled modules and log issues to the console.

    Missing permissions do not stop the bot; they are reported so operators
    can fix configuration before features fail at runtime.
    """
    me = guild.me
    if me is None:
        logger.error("Startup checks skipped: guild.me is unavailable")
        return

    issues: list[str] = []

    for item in collect_guild_mute_permission_issues(me):
        issues.append(f"[channel_mutes] {item}")

    if media_cleanup_config.enabled:
        for channel_id in media_cleanup_config.channel_ids:
            channel = await resolve_text_channel(guild, channel_id)
            if channel is None:
                issues.append(
                    f"[media_cleanup] канал {channel_id} не найден или не текстовый"
                )
                continue

            channel_issues = collect_media_cleanup_channel_issues(channel, me)
            for item in channel_issues:
                issues.append(
                    f"[media_cleanup] #{channel.name} ({channel.id}): нет права «{item}»"
                )

    if not issues:
        logger.info("Startup permission checks passed")
        return

    logger.warning(
        "Startup permission checks found %s issue(s):\n%s",
        len(issues),
        "\n".join(f"  • {item}" for item in issues),
    )
