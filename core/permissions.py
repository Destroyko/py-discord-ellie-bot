"""Moderation permission checks."""

from __future__ import annotations

import discord

from core.config_loader import AppConfig
from modules.channel_mutes.mute_scope import MuteScope

_MSG_DENIED = "Нельзя применить наказание к этому участнику."


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
    scope: MuteScope = MuteScope.CHAT_ONLY,
) -> tuple[bool, str | None]:
    """
    Check whether the bot can apply overwrites to the target for ``scope``.

    Missing permissions are collected in discovery order and returned as a
    bullet list so the moderator sees exactly what is lacking.

    :returns: (ok, error_message_ru)
    """
    me = guild.me
    if me is None:
        return False, "Не могу выдать наказание: бот не найден на сервере."

    aspect = _scope_aspect(scope)
    missing: list[str] = []

    if not me.guild_permissions.manage_channels:
        missing.append("право сервера «Управление каналами»")
    if not me.guild_permissions.manage_roles:
        missing.append("право сервера «Управление ролями»")
    if scope.affects_threads and not bool(
        getattr(me.guild_permissions, "send_messages_in_threads", False)
    ):
        missing.append("право сервера «Отправка сообщений в ветках»")

    if channel is not None:
        channel_permissions = channel.permissions_for(me)
        if not channel_permissions.manage_channels:
            missing.append(f"право «Управление каналом» в канале #{channel.name}")
        if not channel_permissions.manage_roles:
            missing.append(
                f"право «Управление правами» в канале #{channel.name} "
                f"(для управления общением {aspect})"
            )
        if scope.affects_threads and not bool(
            getattr(channel_permissions, "send_messages_in_threads", False)
        ):
            missing.append(
                f"право «Отправка сообщений в ветках» в канале #{channel.name}"
            )

    if me.top_role <= target.top_role:
        missing.append("роль бота должна быть выше роли пользователя")

    if missing:
        bullet_list = "\n".join(f"• {item}" for item in missing)
        return False, f"Не могу выдать наказание. Не хватает прав:\n{bullet_list}"

    return True, None


def _scope_aspect(scope: MuteScope) -> str:
    """Russian fragment describing what the scope restricts."""
    if scope is MuteScope.CHAT_ONLY:
        return "в чате"
    if scope is MuteScope.THREADS_ONLY:
        return "в ветках"
    return "в чате и ветках"
