"""Permission checks for media channel cleanup."""

from __future__ import annotations

import discord


def collect_media_cleanup_channel_issues(
    channel: discord.TextChannel,
    member: discord.Member,
) -> list[str]:
    """Return human-readable missing permissions for cleanup in a channel."""
    perms = channel.permissions_for(member)
    missing: list[str] = []

    if not perms.view_channel:
        missing.append("Просмотр канала")
    if not perms.read_message_history:
        missing.append("Чтение истории сообщений")
    if not perms.manage_messages:
        missing.append("Управление сообщениями")

    return missing
