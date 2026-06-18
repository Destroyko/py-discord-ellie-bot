"""Discord channel permission overwrite apply/revert."""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.abc import _Overwrites

from core.channel_context import MuteChannel
from core.exceptions import DiscordActionError
from modules.channel_mutes.mute_scope import MuteScope
from modules.channel_mutes.permissions_bits import (
    BitPair,
    CREATE_PUBLIC_THREADS_BIT,
    SEND_MESSAGES_IN_THREADS_BIT,
    applied_bit_pairs,
    capture_state_for_scope,
    compute_reverted_pair,
    deny_flag_value_for_scope,
    scope_bit_pairs,
)

logger = logging.getLogger("ellie_bot")


class OverwriteManager:
    """Apply and revert send-message deny bits for a member in a channel."""

    @staticmethod
    def read_scope_state(
        channel: MuteChannel,
        member: discord.Member | discord.abc.Snowflake,
        scope: MuteScope,
    ) -> dict[str, Any]:
        """Capture tri-state of the bits managed by ``scope`` before mute."""
        existing = channel.overwrites_for(member)
        return capture_state_for_scope(existing, scope)

    async def apply_mute(
        self,
        channel: MuteChannel,
        member: discord.Member,
        scope: MuteScope,
    ) -> list[BitPair]:
        """
        Merge the scope's deny bits into the member overwrite.

        For ``MuteScope.FORUM``, tries both thread bits in one call; on
        ``HTTPException`` retries with ``send_messages_in_threads`` only.

        :returns: list of (snapshot_key, bit) pairs actually applied.
        """
        if scope is MuteScope.FORUM:
            return await self._apply_forum_mute(channel, member)

        current = channel.overwrites_for(member)
        allow, deny = current.pair()
        new_deny = deny.value | deny_flag_value_for_scope(scope)
        new_overwrite = discord.PermissionOverwrite.from_pair(
            discord.Permissions(allow.value),
            discord.Permissions(new_deny),
        )
        await channel.set_permissions(member, overwrite=new_overwrite)
        return list(scope_bit_pairs(scope))

    async def _apply_forum_mute(
        self,
        channel: MuteChannel,
        member: discord.Member,
    ) -> list[BitPair]:
        current = channel.overwrites_for(member)
        allow, deny = current.pair()
        full_deny = deny.value | SEND_MESSAGES_IN_THREADS_BIT | CREATE_PUBLIC_THREADS_BIT
        full_overwrite = discord.PermissionOverwrite.from_pair(
            discord.Permissions(allow.value),
            discord.Permissions(full_deny),
        )
        try:
            await channel.set_permissions(member, overwrite=full_overwrite)
            return list(scope_bit_pairs(MuteScope.FORUM))
        except discord.HTTPException as exc:
            send_only_deny = deny.value | SEND_MESSAGES_IN_THREADS_BIT
            send_overwrite = discord.PermissionOverwrite.from_pair(
                discord.Permissions(allow.value),
                discord.Permissions(send_only_deny),
            )
            try:
                await channel.set_permissions(member, overwrite=send_overwrite)
            except discord.HTTPException as send_exc:
                raise DiscordActionError(
                    f"Не могу выдать наказание: "
                    f"{send_exc.text if hasattr(send_exc, 'text') else send_exc}"
                ) from send_exc
            logger.warning(
                "create_public_threads deny failed for user %s in forum %s, "
                "applied send_messages_in_threads only: %s",
                member.id,
                channel.id,
                exc.text if hasattr(exc, "text") else exc,
            )
            return [
                pair
                for pair in scope_bit_pairs(MuteScope.FORUM)
                if pair[1] == SEND_MESSAGES_IN_THREADS_BIT
            ]

    async def revert_mute(
        self,
        channel: MuteChannel,
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
        channel: MuteChannel,
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
        channel: MuteChannel,
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
        channel: MuteChannel,
        member: discord.Member,
        snapshot: dict[str, Any] | None,
        applied_pairs: list[BitPair],
    ) -> None:
        """Revert Discord state after DB/scheduling failure."""
        if not applied_pairs:
            return
        try:
            await self.revert_mute(channel, member, snapshot, applied_pairs)
        except discord.HTTPException:
            logger.exception(
                "Failed to rollback overwrite for user %s in channel %s",
                member.id,
                channel.id,
            )

    def pairs_for_revert(
        self,
        scope: MuteScope,
        snapshot: dict[str, Any] | None,
    ) -> list[BitPair]:
        """Resolve which bit pairs to revert for a mute record."""
        return applied_bit_pairs(scope, snapshot)
