"""Discord channel permission overwrite apply/revert."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.abc import _Overwrites

from modules.channel_mutes.mute_scope import MuteScope
from modules.channel_mutes.permissions_bits import (
    capture_state_for_scope,
    compute_reverted_pair,
    deny_flag_value_for_scope,
)

logger = logging.getLogger("ellie_bot")

# A (snapshot_key, permission_bit) pair, as produced by permissions_bits.
BitPair = tuple[str, int]


class OverwriteManager:
    """Apply and revert send-message deny bits for a member in a text channel."""

    @staticmethod
    def read_scope_state(
        channel: discord.TextChannel,
        member: discord.Member | discord.abc.Snowflake,
        scope: MuteScope,
    ) -> dict[str, Any]:
        """Capture tri-state of the bits managed by ``scope`` before mute."""
        existing = channel.overwrites_for(member)
        return capture_state_for_scope(existing, scope)

    async def apply_mute(
        self,
        channel: discord.TextChannel,
        member: discord.Member,
        scope: MuteScope,
    ) -> None:
        """Merge the scope's deny bits into the member overwrite."""
        current = channel.overwrites_for(member)
        allow, deny = current.pair()
        new_deny = deny.value | deny_flag_value_for_scope(scope)
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
        pairs: list[BitPair],
    ) -> None:
        """Revert only ``pairs`` bits for a member, restoring prior state."""
        await self.revert_mute_by_user_id(
            channel,
            member.id,
            snapshot,
            pairs,
            member=member,
        )

    async def revert_mute_by_user_id(
        self,
        channel: discord.TextChannel,
        user_id: int,
        snapshot: dict[str, Any] | None,
        pairs: list[BitPair],
        *,
        member: discord.Member | None = None,
    ) -> None:
        """
        Revert only ``pairs`` bits for user_id (member on guild or left).

        Bits outside ``pairs`` are preserved so an independent mute keeps its
        deny in place. If the overwrite becomes empty, it is deleted.
        """
        lookup: discord.Member | discord.Object = (
            member if member is not None else discord.Object(id=user_id)
        )
        current = channel.overwrites_for(lookup)
        allow, deny = current.pair()
        new_allow, new_deny = compute_reverted_pair(allow, deny, snapshot, pairs)

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
        pairs: list[BitPair],
    ) -> None:
        """Revert Discord state after DB/scheduling failure."""
        try:
            await self.revert_mute(channel, member, snapshot, pairs)
        except discord.HTTPException:
            logger.exception(
                "Failed to rollback overwrite for user %s in channel %s",
                member.id,
                channel.id,
            )
