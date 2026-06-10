"""Slash commands for channel mutes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from core.channel_context import (
    ChannelKind,
    InvocationContext,
    assert_commands_allowed_in_channel,
    is_ephemeral_mute_command_reply,
    is_ephemeral_reply,
    resolve_invocation_channel,
    resolve_mute_target,
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
from modules.channel_mutes.mute_scope import (
    COMMAND_SCOPE_ALL,
    COMMAND_SCOPE_CHAT,
    COMMAND_SCOPE_THREADS,
    MuteScope,
    scope_from_command_value,
    scope_place_phrase,
)
from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.service import ChannelMuteService
from modules.channel_mutes.unmute_confirm_view import (
    UnmuteConfirmView,
    build_confirm_description,
    format_batch_summary,
)
from modules.channel_mutes.unmute_plan import (
    collect_unmute_records,
    unique_channel_ids,
)
from modules.channel_mutes.user_resolver import resolve_user

logger = logging.getLogger("ellie_bot")
_MSK = ZoneInfo("Europe/Moscow")

_SCOPE_CHOICES = [
    app_commands.Choice(name="чат", value=COMMAND_SCOPE_CHAT),
    app_commands.Choice(name="ветки", value=COMMAND_SCOPE_THREADS),
    app_commands.Choice(name="чат и ветки", value=COMMAND_SCOPE_ALL),
]


def _format_expire_msk(expire_at: datetime) -> str:
    """Format expiry datetime in Moscow time for moderator-facing messages."""
    if expire_at.tzinfo is None:
        expire_at = expire_at.replace(tzinfo=timezone.utc)
    return expire_at.astimezone(_MSK).strftime("%Y-%m-%d %H:%M МСК")


def _channel_mention(guild: discord.Guild, channel_id: int) -> str:
    """Clickable channel reference (<#id>); falls back to id if channel not cached."""
    ch = guild.get_channel(channel_id)
    if isinstance(ch, discord.abc.GuildChannel):
        return ch.mention
    return f"<#{channel_id}>"


def _invocation_parent_channel_id(invocation: InvocationContext) -> int:
    """Parent text channel id for unmute in the current channel or thread."""
    channel = invocation.channel
    if isinstance(channel, discord.Thread):
        if channel.parent_id is None:
            raise ValidationError("Не удалось определить родительский канал ветки.")
        return channel.parent_id
    return channel.id


def _active_mute_target_label(scope: MuteScope, channel_ref: str) -> str:
    """Human-readable target label for /active_mutes, by scope."""
    if scope is MuteScope.THREADS_ONLY:
        return f"только ветки чата {channel_ref}"
    if scope is MuteScope.CHAT_AND_THREADS:
        return f"чат {channel_ref} и его ветки"
    return channel_ref


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
        description="Временно запретить пользователю писать в канал или ветках",
    )
    @app_commands.describe(
        user="Пользователь",
        duration="Длительность (10m, 2h, 3d)",
        reason="Причина",
        channel="Целевой канал или ветка (обязательно в бот-командах)",
        scope="Где запретить: чат / ветки / чат и ветки",
    )
    @app_commands.choices(scope=_SCOPE_CHOICES)
    async def mute_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str,
        reason: str | None = None,
        channel: discord.TextChannel | discord.Thread | None = None,
        scope: str | None = None,
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

            target = resolve_mute_target(invocation, channel, scope, self.config)
            overwrite_channel = target.overwrite_channel

            target_member = await resolve_user(guild, user)

            allowed, msg = can_mute_target(moderator, target_member, self.config)
            if not allowed:
                raise TargetNotAllowedError(msg or "Нельзя применить наказание к этому участнику.")

            ok, bot_msg = bot_can_moderate_member(
                guild,
                target_member,
                overwrite_channel,
                target.scope,
            )
            if not ok:
                raise PermissionDeniedError(bot_msg or "Нельзя выдать наказание.")
            delta = parse_duration(duration)
            duration_text = duration.strip()
            mute, extended = await self.service.mute_channel(
                guild=guild,
                channel=overwrite_channel,
                target=target_member,
                moderator=moderator,
                duration_delta=delta,
                duration_text=duration_text,
                reason=reason,
                scope=target.scope,
            )
            place = scope_place_phrase(target.scope, overwrite_channel.mention)
            verb = "обновлено" if extended else "выдано"
            text = f"Наказание {verb}: {target_member.mention}, {place}, срок {duration_text}"
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
        description="Снять запрет на отправку сообщений в канале или ветках",
    )
    @app_commands.describe(
        user="Пользователь",
        channel="Канал или ветка (в бот-командах можно не указывать)",
        scope="Откуда снять: чат / ветки / чат и ветки",
    )
    @app_commands.choices(scope=_SCOPE_CHOICES)
    async def unmute_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        channel: discord.TextChannel | discord.Thread | None = None,
        scope: str | None = None,
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

            target_member = await resolve_user(guild, user)

            if channel is not None:
                target = resolve_mute_target(invocation, channel, scope, self.config)
                overwrite_channel = target.overwrite_channel
                place = scope_place_phrase(target.scope, overwrite_channel.mention)

                existing = self.repository.get_by_keys(
                    guild.id, overwrite_channel.id, target_member.id, target.scope
                )
                if existing is None:
                    raise ValidationError(
                        f"Пользователь не ограничен в общении {place}."
                    )

                removed = await self.service.unmute_channel(
                    guild=guild,
                    channel=overwrite_channel,
                    target=target_member,
                    moderator=moderator,
                    scope=target.scope,
                )
                if not removed:
                    raise ValidationError(
                        f"Пользователь не ограничен в общении {place}."
                    )

                description = f"Запрет снят: {target_member.mention}, {place}"
                embed_color = discord.Color.green()
            else:
                scope_filter = (
                    scope_from_command_value(scope) if scope is not None else None
                )
                channel_id_filter = (
                    None
                    if invocation.kind == ChannelKind.MOD_COMMANDS
                    else _invocation_parent_channel_id(invocation)
                )
                records = collect_unmute_records(
                    self.repository,
                    guild.id,
                    target_member.id,
                    channel_id=channel_id_filter,
                    scope_filter=scope_filter,
                )
                if not records:
                    raise ValidationError(
                        "Пользователь не ограничен в общении в выбранных каналах."
                    )

                if (
                    len(unique_channel_ids(records)) >= 2
                    and invocation.kind == ChannelKind.MOD_COMMANDS
                ):
                    confirm_embed = discord.Embed(
                        description=build_confirm_description(
                            guild, target_member, records
                        ),
                        color=discord.Color.gold(),
                    )
                    view = UnmuteConfirmView(
                        self.service,
                        guild=guild,
                        target=target_member,
                        moderator=moderator,
                        records=records,
                    )
                    await interaction.followup.send(
                        embed=confirm_embed,
                        view=view,
                        ephemeral=True,
                    )
                    return

                result = await self.service.unmute_records_batch(
                    guild=guild,
                    target=target_member,
                    moderator=moderator,
                    records=records,
                )
                if not result.succeeded and not result.failed:
                    raise ValidationError(
                        "Пользователь не ограничен в общении в выбранных каналах."
                    )
                description = format_batch_summary(result)
                if result.failed and not result.succeeded:
                    embed_color = discord.Color.red()
                elif result.failed:
                    embed_color = discord.Color.orange()
                else:
                    embed_color = discord.Color.green()

            embed = discord.Embed(
                description=description,
                color=embed_color,
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
                    channel_ref = _channel_mention(guild, mute.channel_id)
                    label = _active_mute_target_label(mute.scope, channel_ref)
                    exp = _format_expire_msk(mute.expire_at)
                    reason = mute.reason or "—"
                    lines.append(f"• {label} — до {exp}, причина: {reason}")
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
