"""Channel invocation and target resolution for moderation commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import discord

from core.config_loader import AppConfig
from core.exceptions import ValidationError
from modules.channel_mutes.mute_scope import (
    MuteScope,
    scope_from_command_value,
)


class ChannelKind(Enum):
    """Classification of a text channel for command routing."""

    PUBLIC = "public"
    MOD_COMMANDS = "mod_commands"
    BOT_LOGS = "bot_logs"


@dataclass(frozen=True)
class InvocationContext:
    """Resolved context for where a slash command was invoked."""

    kind: ChannelKind
    channel: discord.TextChannel | discord.Thread


@dataclass(frozen=True)
class TargetChannelContext:
    """Resolved punishment target channel."""

    channel: discord.TextChannel
    channel_param_required: bool


@dataclass(frozen=True)
class MuteTarget:
    """Resolved mute application target.

    ``overwrite_channel`` is the text channel whose permission overwrites are
    edited (the parent channel when a thread was targeted).
    """

    overwrite_channel: discord.TextChannel
    scope: MuteScope
    channel_param_required: bool
    target_is_thread: bool


def classify_channel(channel_id: int, config: AppConfig) -> ChannelKind:
    """Map a channel id to its moderation category."""
    if channel_id == config.bot_logs_channel_id:
        return ChannelKind.BOT_LOGS
    if channel_id == config.moderator_commands_channel_id:
        return ChannelKind.MOD_COMMANDS
    return ChannelKind.PUBLIC


def resolve_invocation_channel(
    interaction: discord.Interaction,
    config: AppConfig,
) -> InvocationContext:
    """
    Resolve the channel (or thread) where the command was invoked.

    Threads inherit the routing classification of their parent text channel
    for special channels (mod-commands / bot-logs).

    :raises ValidationError: if not a text channel or text thread.
    """
    channel = interaction.channel
    if interaction.guild is None or not isinstance(
        channel, (discord.TextChannel, discord.Thread)
    ):
        raise ValidationError("Команда доступна только в текстовых каналах и ветках.")

    classify_id = channel.id
    if isinstance(channel, discord.Thread) and channel.parent_id is not None:
        if classify_channel(channel.parent_id, config) != ChannelKind.PUBLIC:
            classify_id = channel.parent_id

    kind = classify_channel(classify_id, config)
    return InvocationContext(kind=kind, channel=channel)


def assert_commands_allowed_in_channel(kind: ChannelKind, *, for_help: bool = False, for_active_mutes: bool = False) -> None:
    """
    Enforce channel restrictions for command invocation.

    :raises ValidationError: when the command cannot run in this channel kind.
    """
    if kind == ChannelKind.BOT_LOGS:
        raise ValidationError("Эту команду нельзя использовать в канале логов ботов.")

    if for_help or for_active_mutes:
        if kind != ChannelKind.MOD_COMMANDS:
            raise ValidationError(
                "Эту команду можно использовать только в канале бот-команд."
            )


def resolve_mute_target(
    invocation: InvocationContext,
    channel_param: discord.TextChannel | discord.Thread | None,
    scope_value: str | None,
    config: AppConfig,
) -> MuteTarget:
    """
    Resolve where mute/unmute applies and with which :class:`MuteScope`.

    Thread targets edit the parent text channel's overwrites. The default
    scope, when not given, is ``chat`` for text channels and ``threads`` for
    thread targets.

    :raises ValidationError: on missing required param, forbidden target,
        forum threads, or an invalid scope/target combination.
    """
    if invocation.kind == ChannelKind.MOD_COMMANDS:
        if channel_param is None:
            raise ValidationError(
                "Укажите канал: параметр channel обязателен в этом чате."
            )
        target = channel_param
        required = True
    else:
        target = channel_param or invocation.channel
        required = False

    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        raise ValidationError("Команда доступна только в текстовых каналах и ветках.")

    target_is_thread = isinstance(target, discord.Thread)
    if target_is_thread:
        parent = target.parent
        if not isinstance(parent, discord.TextChannel):
            raise ValidationError(
                "Наказание поддерживается только в текстовых ветках (форумы не поддерживаются)."
            )
        overwrite_channel = parent
    else:
        overwrite_channel = target

    target_kind = classify_channel(overwrite_channel.id, config)
    if target_kind in (ChannelKind.MOD_COMMANDS, ChannelKind.BOT_LOGS):
        raise ValidationError("Нельзя выдать наказание в этот канал.")

    scope = _resolve_scope(scope_value, target_is_thread)

    return MuteTarget(
        overwrite_channel=overwrite_channel,
        scope=scope,
        channel_param_required=required,
        target_is_thread=target_is_thread,
    )


def _resolve_scope(scope_value: str | None, target_is_thread: bool) -> MuteScope:
    """Resolve effective scope from the command value and the target type."""
    if scope_value is None:
        return MuteScope.THREADS_ONLY if target_is_thread else MuteScope.CHAT_ONLY

    scope = scope_from_command_value(scope_value)
    if target_is_thread and scope is MuteScope.CHAT_ONLY:
        raise ValidationError(
            "Для ветки нельзя выбрать «только чат». Выберите «ветки» или «чат и ветки»."
        )
    return scope


def is_ephemeral_reply(invocation_kind: ChannelKind) -> bool:
    """Whether bot replies to the moderator should be ephemeral."""
    return invocation_kind == ChannelKind.PUBLIC


def is_ephemeral_mute_command_reply(invocation_kind: ChannelKind) -> bool:
    """
    Ephemeral slash ack for /mute_user.

    In public channels the audit log is the shared record; in mod-commands
    ModeratorNotifier posts the visible notice — the slash reply is private.
    """
    return invocation_kind in (ChannelKind.PUBLIC, ChannelKind.MOD_COMMANDS)
