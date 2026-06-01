"""Discord channel permission overwrite apply/revert."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.abc import _Overwrites

from modules.channel_mutes.permissions_bits import (
    SEND_MESSAGES_BIT,
    SNAPSHOT_KEY_SEND_MESSAGES,
    capture_send_messages_state,
    compute_reverted_send_messages_pair,
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
        await self.revert_mute_by_user_id(
            channel,
            member.id,
            snapshot,
            member=member,
        )

    async def revert_mute_by_user_id(
        self,
        channel: discord.TextChannel,
        user_id: int,
        snapshot: dict[str, Any] | None,
        *,
        member: discord.Member | None = None,
    ) -> None:
        """
        Revert send_messages deny for user_id (member on guild or left).

        Uses set_permissions when member is known; otherwise channel permission HTTP
        endpoints (Discord allows member overwrites by id even if not in guild).
        """
        lookup: discord.Member | discord.Object = (
            member if member is not None else discord.Object(id=user_id)
        )
        current = channel.overwrites_for(lookup)
        allow, deny = current.pair()
        new_allow, new_deny = compute_reverted_send_messages_pair(allow, deny, snapshot)

        if new_allow.value == 0 and new_deny.value == 0:
            await self._apply_channel_permissions(
                channel,
                user_id,
                overwrite=None,
                member=member,
            )
            return

        new_overwrite = discord.PermissionOverwrite.from_pair(new_allow, new_deny)
        await self._apply_channel_permissions(
            channel,
            user_id,
            overwrite=new_overwrite,
            member=member,
        )

    async def _apply_channel_permissions(
        self,
        channel: discord.TextChannel,
        user_id: int,
        *,
        overwrite: discord.PermissionOverwrite | None,
        member: discord.Member | None,
    ) -> None:
        if member is not None:
            await channel.set_permissions(member, overwrite=overwrite)
            return

        http = channel._state.http
        if overwrite is None:
            await http.delete_channel_permissions(channel.id, user_id)
            return

        allow, deny = overwrite.pair()
        await http.edit_channel_permissions(
            channel.id,
            user_id,
            str(allow.value),
            str(deny.value),
            _Overwrites.MEMBER,
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
