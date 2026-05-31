"""Unified moderator interaction responses."""

from __future__ import annotations

import logging
import traceback

import discord

from core.channel_context import ChannelKind, is_ephemeral_reply
from core.config_loader import AppConfig

logger = logging.getLogger("ellie_bot")

MSG_WRONG_GUILD = "Неверный guild_id в конфигурации бота."


def assert_guild(interaction: discord.Interaction, config: AppConfig) -> bool:
    """
    Verify interaction belongs to the configured guild.

    :returns: True if valid; False if wrong guild (caller should stop).
    """
    if interaction.guild is None or interaction.guild.id != config.guild_id:
        return False
    return True


async def reply_moderator(
    interaction: discord.Interaction,
    text: str,
    *,
    config: AppConfig,
    invocation_kind: ChannelKind,
    success: bool = False,
    ephemeral: bool | None = None,
) -> None:
    """
    Send a response to the invoking moderator in-channel.

    Uses ephemeral in public channels unless overridden.
    """
    if ephemeral is None:
        ephemeral = is_ephemeral_reply(invocation_kind)

    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(text, ephemeral=ephemeral)


async def defer_moderator(
    interaction: discord.Interaction,
    *,
    invocation_kind: ChannelKind,
    ephemeral: bool | None = None,
) -> None:
    """Defer the interaction for long-running work."""
    if ephemeral is None:
        ephemeral = is_ephemeral_reply(invocation_kind)
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)


async def reply_wrong_guild(interaction: discord.Interaction) -> None:
    """Reply when guild_id does not match configuration."""
    ephemeral = True
    if not interaction.response.is_done():
        await interaction.response.send_message(MSG_WRONG_GUILD, ephemeral=ephemeral)
    else:
        await interaction.followup.send(MSG_WRONG_GUILD, ephemeral=ephemeral)


async def reply_validation(
    interaction: discord.Interaction,
    message: str,
    *,
    config: AppConfig,
    invocation_kind: ChannelKind,
) -> None:
    """Send a validation error to the moderator."""
    await reply_moderator(
        interaction,
        message,
        config=config,
        invocation_kind=invocation_kind,
        success=False,
    )


async def reply_internal_error(
    interaction: discord.Interaction,
    exc: BaseException,
    *,
    config: AppConfig,
    invocation_kind: ChannelKind,
) -> None:
    """Log traceback and notify moderator generically."""
    logger.exception("Command failed: %s", exc)
    logger.debug(traceback.format_exc())
    await reply_moderator(
        interaction,
        "Не удалось выполнить команду. Попробуйте позже или обратитесь к администратору.",
        config=config,
        invocation_kind=invocation_kind,
        success=False,
    )
