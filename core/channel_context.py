"""Channel invocation and target resolution for moderation commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import discord

from core.config_loader import AppConfig
from core.exceptions import ValidationError


class ChannelKind(Enum):
    """Classification of a text channel for command routing."""

    PUBLIC = "public"
    MOD_COMMANDS = "mod_commands"
    BOT_LOGS = "bot_logs"


@dataclass(frozen=True)
class InvocationContext:
    """Resolved context for where a slash command was invoked."""

    kind: ChannelKind
    channel: discord.TextChannel


@dataclass(frozen=True)
class TargetChannelContext:
    """Resolved punishment target channel."""

    channel: discord.TextChannel
    channel_param_required: bool


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
  Resolve the channel where the command was invoked.

  :raises ValidationError: if not a text channel.
    """
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        raise ValidationError("Команда доступна только в текстовых каналах.")

    kind = classify_channel(interaction.channel.id, config)
    return InvocationContext(kind=kind, channel=interaction.channel)


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


def resolve_target_channel(
    invocation: InvocationContext,
    channel_param: discord.TextChannel | None,
    config: AppConfig,
) -> TargetChannelContext:
    """
    Resolve the channel where mute/unmute applies.

    :raises ValidationError: on missing required param or forbidden target.
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

    if not isinstance(target, discord.TextChannel):
        raise ValidationError("Команда доступна только в текстовых каналах.")

    target_kind = classify_channel(target.id, config)
    if target_kind in (ChannelKind.MOD_COMMANDS, ChannelKind.BOT_LOGS):
        raise ValidationError("Нельзя выдать наказание в этот канал.")

    return TargetChannelContext(channel=target, channel_param_required=required)


def is_ephemeral_reply(invocation_kind: ChannelKind) -> bool:
    """Whether bot replies to the moderator should be ephemeral."""
    return invocation_kind == ChannelKind.PUBLIC
