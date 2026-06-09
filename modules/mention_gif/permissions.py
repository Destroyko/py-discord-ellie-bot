"""Channel permission checks for sending GIF attachments."""

from __future__ import annotations

import discord


def can_send_gif(
    channel: discord.abc.GuildChannel,
    member: discord.Member | None,
) -> bool:
    """Return True if ``member`` may reply with a file attachment in ``channel``."""
    if member is None:
        return False
    perms = channel.permissions_for(member)
    return bool(
        perms.view_channel and perms.send_messages and perms.attach_files
    )
