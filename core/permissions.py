"""Moderation permission checks."""

from __future__ import annotations

import discord

from core.config_loader import AppConfig

_MSG_DENIED = "Нельзя применить наказание к этому участнику."
_PERMISSION_LABELS_RU = {
    "manage_channels": "Управление каналами",
    "manage_roles": "Управление ролями",
}


def can_moderate(member: discord.Member, config: AppConfig) -> bool:
    """
    Return True if the member may use moderation slash commands.

    Allowed if guild Administrator or any configured moderator role.
    """
    if member.guild_permissions.administrator:
        return True
    member_role_ids = {role.id for role in member.roles}
    return bool(member_role_ids & set(config.moderator_role_ids))


def best_role_rank(member: discord.Member, ordered_role_ids: tuple[int, ...]) -> int | None:
    """
    Return the best (highest) rank index for member among configured roles.

    Lower index = higher in hierarchy (first in roles.yaml is senior).
    None if the member has none of the configured roles.
    """
    rank_by_id = {role_id: index for index, role_id in enumerate(ordered_role_ids)}
    ranks = [rank_by_id[role.id] for role in member.roles if role.id in rank_by_id]
    if not ranks:
        return None
    return min(ranks)


def can_mute_target(
    moderator: discord.Member,
    target: discord.Member,
    config: AppConfig,
) -> tuple[bool, str | None]:
    """
    Return whether ``moderator`` may mute ``target`` per policy.

    Non-admin moderators may only mute members at a lower tier in
    ``roles.yaml`` (later in the list) or with no listed moderator role.

    :returns: (allowed, error_message_ru)
    """
    if target.id == moderator.id:
        return False, _MSG_DENIED

    if target.bot:
        return False, _MSG_DENIED

    if target.id == target.guild.owner_id:
        return False, _MSG_DENIED

    if target.guild_permissions.administrator:
        return False, _MSG_DENIED

    if moderator.guild_permissions.administrator:
        return True, None

    mod_rank = best_role_rank(moderator, config.moderator_role_ids)
    if mod_rank is None:
        return False, _MSG_DENIED

    target_rank = best_role_rank(target, config.moderator_role_ids)
    if target_rank is None:
        return True, None

    if mod_rank < target_rank:
        return True, None

    return False, _MSG_DENIED


def bot_can_moderate_member(
    guild: discord.Guild,
    target: discord.Member,
    channel: discord.abc.GuildChannel | None = None,
) -> tuple[bool, str | None]:
    """
    Check whether the bot can apply overwrites to the target.

    :returns: (ok, error_message_ru)
    """
    me = guild.me
    if me is None:
        return False, "Не могу выдать наказание: бот не найден на сервере."

    missing_guild_permissions = _missing_permissions(me.guild_permissions)
    if missing_guild_permissions:
        return (
            False,
            "Не могу выдать наказание: у бота нет серверных прав: "
            f"{_format_permissions_list(missing_guild_permissions)}.",
        )

    if channel is not None:
        channel_permissions = channel.permissions_for(me)
        missing_channel_permissions = _missing_permissions(channel_permissions)
        if missing_channel_permissions:
            return (
                False,
                "Не могу выдать наказание: у бота нет прав в канале "
                f"#{channel.name}: {_format_permissions_list(missing_channel_permissions)}.",
            )

    if me.top_role <= target.top_role:
        return False, "Не могу выдать наказание: роль бота ниже роли пользователя."

    return True, None


def _missing_permissions(permissions: discord.Permissions | object) -> list[str]:
    missing: list[str] = []
    for key in ("manage_channels", "manage_roles"):
        if not bool(getattr(permissions, key, False)):
            missing.append(_PERMISSION_LABELS_RU[key])
    return missing


def _format_permissions_list(permission_names: list[str]) -> str:
    return ", ".join(f"«{name}»" for name in permission_names)
