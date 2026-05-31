"""Discord channel permission overwrite apply/revert."""

from __future__ import annotations

import logging
from typing import Any

import discord

from modules.channel_mutes.permissions_bits import (
    SEND_MESSAGES_BIT,
    SNAPSHOT_KEY_SEND_MESSAGES,
    capture_send_messages_state,
    has_our_send_messages_deny,
)

logger = logging.getLogger("ellie_bot")


class OverwriteManager:
    """Apply and revert send_messages deny for a member in a text channel."""

    async def capture_snapshot(
        self,
        channel: discord.TextChannel,
        member: discord.Member,
    ) -> dict[str, Any] | None:
        """Capture bot-managed permission state before mute."""
        existing = channel.overwrites_for(member)
        if existing.pair() == (discord.Permissions.none(), discord.Permissions.none()):
            return None
        state = capture_send_messages_state(existing)
        if state.get(SNAPSHOT_KEY_SEND_MESSAGES) is None and not has_our_send_messages_deny(existing):
            return None
        return state

    async def apply_mute(
        self,
        channel: discord.TextChannel,
        member: discord.Member,
    ) -> None:
        """Merge send_messages deny into member overwrite."""
        current = channel.overwrites_for(member)
        allow, deny = current.pair()
        new_deny = deny.value | SEND_MESSAGES_BIT
        new_overwrite = discord.PermissionOverwrite.from_pair(
            discord.Permissions(allow.value),
            discord.Permissions(new_deny),
        )
        await channel.set_permissions(member, overwrite=new_overwrite)

    async def revert_mute(
        self,
        channel: discord.TextChannel,
        member: discord.Member,
        snapshot: dict[str, Any] | None,
    ) -> None:
        """
        Remove only our send_messages deny and restore prior state from snapshot.

        If overwrite becomes empty, delete it.
        """
        current = channel.overwrites_for(member)
        allow, deny = current.pair()

        # Remove send_messages from deny
        new_deny_value = deny.value & ~SEND_MESSAGES_BIT
        prior = None if snapshot is None else snapshot.get(SNAPSHOT_KEY_SEND_MESSAGES)

        if prior is True:
            new_allow_value = allow.value | SEND_MESSAGES_BIT
            new_deny_value = new_deny_value & ~SEND_MESSAGES_BIT
        elif prior is False:
            new_allow_value = allow.value & ~SEND_MESSAGES_BIT
            new_deny_value = new_deny_value | SEND_MESSAGES_BIT
        else:
            new_allow_value = allow.value & ~SEND_MESSAGES_BIT
            new_deny_value = new_deny_value & ~SEND_MESSAGES_BIT

        new_allow = discord.Permissions(new_allow_value)
        new_deny = discord.Permissions(new_deny_value)

        if new_allow.value == 0 and new_deny.value == 0:
            await channel.set_permissions(member, overwrite=None)
            return

        await channel.set_permissions(
            member,
            overwrite=discord.PermissionOverwrite.from_pair(new_allow, new_deny),
        )

    async def rollback_after_failed_db(
        self,
        channel: discord.TextChannel,
        member: discord.Member,
        snapshot: dict[str, Any] | None,
    ) -> None:
        """Revert Discord state after DB/scheduling failure."""
        try:
            await self.revert_mute(channel, member, snapshot)
        except discord.HTTPException:
            logger.exception(
                "Failed to rollback overwrite for user %s in channel %s",
                member.id,
                channel.id,
            )
