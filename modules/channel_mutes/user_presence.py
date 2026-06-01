"""Resolve whether a user is on guild, left, or deleted (for auto-unmute)."""

from __future__ import annotations

from enum import Enum

import discord


class UserPresence(Enum):
    """Guild membership state for a Discord user id."""

    ON_GUILD = "on_guild"
    LEFT_GUILD = "left_guild"
    DELETED = "deleted"


async def resolve_user_presence(
    bot: discord.Client,
    guild: discord.Guild,
    user_id: int,
) -> tuple[UserPresence, discord.Member | None]:
    """
    Classify user for auto-unmute paths.

    Order: fetch_user (deleted?) then fetch_member (on guild?).
    fetch_member 404 alone does not mean deleted account.
    """
    try:
        await bot.fetch_user(user_id)
    except discord.NotFound:
        return UserPresence.DELETED, None

    member = guild.get_member(user_id)
    if member is not None:
        return UserPresence.ON_GUILD, member

    try:
        member = await guild.fetch_member(user_id)
    except discord.NotFound:
        return UserPresence.LEFT_GUILD, None

    return UserPresence.ON_GUILD, member
