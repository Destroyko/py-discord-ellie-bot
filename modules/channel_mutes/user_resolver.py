"""Resolve slash command user parameters to guild members."""

from __future__ import annotations

import discord

from core.exceptions import ValidationError


async def resolve_user(
    guild: discord.Guild,
    user_param: discord.Member | discord.User | str,
) -> discord.Member:
    """
    Resolve a user from slash input (member picker or numeric id string).

    :raises ValidationError: if the user is not on the guild.
    """
    if isinstance(user_param, discord.Member):
        return user_param

    if isinstance(user_param, discord.User):
        member = guild.get_member(user_param.id)
        if member is None:
            try:
                member = await guild.fetch_member(user_param.id)
            except discord.NotFound:
                member = None
        if member is None:
            raise ValidationError("Пользователь не найден на этом сервере.")
        return member

    raw = user_param.strip()
    if not raw.isdigit():
        raise ValidationError("Пользователь не найден на этом сервере.")

    user_id = int(raw)
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            raise ValidationError("Пользователь не найден на этом сервере.") from None
    return member
