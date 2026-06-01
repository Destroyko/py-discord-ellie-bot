"""Slash commands for channel mutes."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.channel_context import (
    assert_commands_allowed_in_channel,
    is_ephemeral_mute_command_reply,
    is_ephemeral_reply,
    resolve_invocation_channel,
    resolve_target_channel,
)
from core.config_loader import AppConfig
from core.exceptions import (
    DiscordActionError,
    PermissionDeniedError,
    TargetNotAllowedError,
    ValidationError,
)
from core.permissions import bot_can_moderate_member, can_moderate, can_mute_target
from core.responses import (
    assert_guild,
    defer_moderator,
    reply_internal_error,
    reply_moderator,
    reply_validation,
    reply_wrong_guild,
)
from modules.channel_mutes.duration import parse_duration
from modules.channel_mutes.help_text import HELP_MESSAGE
from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.service import ChannelMuteService
from modules.channel_mutes.user_resolver import resolve_user

logger = logging.getLogger("ellie_bot")


class ChannelMutesCog(commands.Cog):
    """Slash commands: mute_user, unmute_user, active_mutes, mute_help."""

    def __init__(
        self,
        bot: commands.Bot,
        config: AppConfig,
        service: ChannelMuteService,
        repository: ChannelMuteRepository,
    ) -> None:
        self.bot = bot
        self.config = config
        self.service = service
        self.repository = repository

    async def _base_checks(
        self, interaction: discord.Interaction
    ) -> tuple[discord.Guild, discord.Member] | None:
        if not assert_guild(interaction, self.config):
            await reply_wrong_guild(interaction)
            return None
        if interaction.user is None or not isinstance(interaction.user, discord.Member):
            return None
        if not can_moderate(interaction.user, self.config):
            inv = resolve_invocation_channel(interaction, self.config)
            await reply_validation(
                interaction,
                "У вас нет прав для этой команды.",
                config=self.config,
                invocation_kind=inv.kind,
            )
            return None
        assert interaction.guild is not None
        return interaction.guild, interaction.user

    @app_commands.command(
        name="mute_user",
        description="Временно запретить пользователю писать в канал",
    )
    @app_commands.describe(
        user="Пользователь",
        duration="Длительность (10m, 2h, 3d)",
        reason="Причина",
        channel="Целевой канал (обязательно в бот-командах)",
    )
    async def mute_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str,
        reason: str | None = None,
        channel: discord.TextChannel | None = None,
    ) -> None:
        inv_kind = None
        try:
            base = await self._base_checks(interaction)
            if base is None:
                return
            guild, moderator = base

            invocation = resolve_invocation_channel(interaction, self.config)
            inv_kind = invocation.kind
            assert_commands_allowed_in_channel(invocation.kind)

            mute_reply_ephemeral = is_ephemeral_mute_command_reply(invocation.kind)
            await defer_moderator(
                interaction,
                invocation_kind=invocation.kind,
                ephemeral=mute_reply_ephemeral,
            )

            target_ctx = resolve_target_channel(invocation, channel, self.config)
            target_channel = target_ctx.channel

            target_member = await resolve_user(guild, user)

            allowed, msg = can_mute_target(moderator, target_member, self.config)
            if not allowed:
                raise TargetNotAllowedError(msg or "Нельзя применить наказание к этому участнику.")

            ok, bot_msg = bot_can_moderate_member(guild, target_member)
            if not ok:
                raise PermissionDeniedError(bot_msg or "Нельзя выдать наказание.")
            delta = parse_duration(duration)
            duration_text = duration.strip()
            mute, extended = await self.service.mute_channel(
                guild=guild,
                channel=target_channel,
                target=target_member,
                moderator=moderator,
                duration_delta=delta,
                duration_text=duration_text,
                reason=reason,
            )
            if extended:
                text = (
                    f"Наказание обновлено: {target_member.mention}, "
                    f"канал {target_channel.mention}, срок {duration_text}"
                )
            else:
                text = (
                    f"Наказание выдано: {target_member.mention}, "
                    f"канал {target_channel.mention}, срок {duration_text}"
                )
            await reply_moderator(
                interaction,
                text,
                config=self.config,
                invocation_kind=invocation.kind,
                success=True,
                ephemeral=mute_reply_ephemeral,
            )
        except ValidationError as exc:
            if inv_kind is None:
                try:
                    inv_kind = resolve_invocation_channel(interaction, self.config).kind
                except ValidationError:
                    inv_kind = None
            if inv_kind is not None:
                await reply_validation(
                    interaction,
                    exc.message,
                    config=self.config,
                    invocation_kind=inv_kind,
                    ephemeral=is_ephemeral_mute_command_reply(inv_kind),
                )
        except (TargetNotAllowedError, PermissionDeniedError, DiscordActionError) as exc:
            kind = inv_kind or resolve_invocation_channel(interaction, self.config).kind
            await reply_validation(
                interaction,
                exc.message,
                config=self.config,
                invocation_kind=kind,
                ephemeral=is_ephemeral_mute_command_reply(kind),
            )
        except Exception as exc:
            kind = inv_kind
            if kind is None:
                try:
                    kind = resolve_invocation_channel(interaction, self.config).kind
                except Exception:
                    kind = None
            if kind is not None:
                await reply_internal_error(
                    interaction,
                    exc,
                    config=self.config,
                    invocation_kind=kind,
                    ephemeral=is_ephemeral_mute_command_reply(kind),
                )

    @app_commands.command(
        name="unmute_user",
        description="Снять запрет на отправку сообщений в канале",
    )
    @app_commands.describe(
        user="Пользователь",
        channel="Канал (обязательно в бот-командах)",
    )
    async def unmute_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        channel: discord.TextChannel | None = None,
    ) -> None:
        inv_kind = None
        try:
            base = await self._base_checks(interaction)
            if base is None:
                return
            guild, moderator = base

            invocation = resolve_invocation_channel(interaction, self.config)
            inv_kind = invocation.kind
            assert_commands_allowed_in_channel(invocation.kind)

            await defer_moderator(interaction, invocation_kind=invocation.kind)

            target_ctx = resolve_target_channel(invocation, channel, self.config)
            target_channel = target_ctx.channel
            target_member = await resolve_user(guild, user)

            existing = self.repository.get_by_keys(
                guild.id, target_channel.id, target_member.id
            )
            if existing is None:
                raise ValidationError(
                    f"Пользователь не ограничен в общении в канале #{target_channel.name}."
                )

            removed = await self.service.unmute_channel(
                guild=guild,
                channel=target_channel,
                target=target_member,
                moderator=moderator,
            )
            if not removed:
                raise ValidationError(
                    f"Пользователь не ограничен в общении в канале #{target_channel.name}."
                )

            embed = discord.Embed(
                description=(
                    f"Запрет снят: {target_member.mention}, "
                    f"канал {target_channel.mention}"
                ),
                color=discord.Color.green(),
            )
            avatar = moderator.avatar or moderator.default_avatar
            embed.set_author(name=moderator.name, icon_url=avatar.url)
            ephemeral = is_ephemeral_reply(invocation.kind)
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        except ValidationError as exc:
            if inv_kind is not None:
                await reply_validation(
                    interaction, exc.message, config=self.config, invocation_kind=inv_kind
                )
        except Exception as exc:
            if inv_kind is not None:
                await reply_internal_error(
                    interaction, exc, config=self.config, invocation_kind=inv_kind
                )

    @app_commands.command(
        name="active_mutes",
        description="Список активных ограничений пользователя по каналам",
    )
    @app_commands.describe(user="Пользователь")
    async def active_mutes(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        inv_kind = None
        try:
            base = await self._base_checks(interaction)
            if base is None:
                return
            guild, _moderator = base

            invocation = resolve_invocation_channel(interaction, self.config)
            inv_kind = invocation.kind
            assert_commands_allowed_in_channel(
                invocation.kind, for_active_mutes=True
            )

            await defer_moderator(interaction, invocation_kind=invocation.kind)

            target_member = await resolve_user(guild, user)

            mutes = self.repository.list_active_for_user(guild.id, target_member.id)

            if not mutes:
                text = "У пользователя нет активных ограничений в каналах."
            else:
                lines = [
                    f"Активные ограничения для {target_member.mention} (`{target_member.id}`):"
                ]
                for mute in mutes:
                    ch = guild.get_channel(mute.channel_id)
                    ch_name = ch.name if isinstance(ch, discord.TextChannel) else str(mute.channel_id)
                    exp = mute.expire_at.strftime("%Y-%m-%d %H:%M UTC")
                    reason = mute.reason or "—"
                    lines.append(f"• #{ch_name} — до {exp}, причина: {reason}")
                text = "\n".join(lines)

            await reply_moderator(
                interaction,
                text,
                config=self.config,
                invocation_kind=invocation.kind,
                success=True,
            )
        except ValidationError as exc:
            if inv_kind is not None:
                await reply_validation(
                    interaction, exc.message, config=self.config, invocation_kind=inv_kind
                )
        except Exception as exc:
            if inv_kind is not None:
                await reply_internal_error(
                    interaction, exc, config=self.config, invocation_kind=inv_kind
                )

    @app_commands.command(
        name="mute_help",
        description="Справка по командам ограничений в каналах",
    )
    async def mute_help(self, interaction: discord.Interaction) -> None:
        inv_kind = None
        try:
            base = await self._base_checks(interaction)
            if base is None:
                return

            invocation = resolve_invocation_channel(interaction, self.config)
            inv_kind = invocation.kind
            assert_commands_allowed_in_channel(invocation.kind, for_help=True)

            await reply_moderator(
                interaction,
                HELP_MESSAGE,
                config=self.config,
                invocation_kind=invocation.kind,
                success=True,
            )
        except ValidationError as exc:
            if inv_kind is not None:
                await reply_validation(
                    interaction, exc.message, config=self.config, invocation_kind=inv_kind
                )
        except Exception as exc:
            if inv_kind is not None:
                await reply_internal_error(
                    interaction, exc, config=self.config, invocation_kind=inv_kind
                )


async def setup_channel_mutes_cog(
    bot: commands.Bot,
    config: AppConfig,
    service: ChannelMuteService,
    repository: ChannelMuteRepository,
) -> ChannelMutesCog:
    """Create and add the channel mutes cog."""
    cog = ChannelMutesCog(bot, config, service, repository)
    await bot.add_cog(cog)
    return cog
