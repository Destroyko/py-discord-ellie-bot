"""Ephemeral confirmation UI for bulk /unmute_user."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from database.models import ChannelMute
from modules.channel_mutes.mute_scope import scope_place_phrase
from modules.channel_mutes.unmute_plan import (
    UnmuteBatchResult,
    group_records_by_channel,
    notification_scope_for_channel,
)

if TYPE_CHECKING:
    from modules.channel_mutes.service import ChannelMuteService

logger = logging.getLogger("ellie_bot")


def format_batch_summary(result: UnmuteBatchResult) -> str:
    """Moderator-facing summary after batch unmute (success and/or partial failure)."""
    lines: list[str] = []
    if result.succeeded:
        lines.append(
            f"Снято {result.record_count} ограничений в {result.channel_count} каналах."
        )
    if result.failed:
        lines.append("Не удалось снять:")
        for record, reason in result.failed:
            channel_ref = f"<#{record.channel_id}>"
            place = scope_place_phrase(record.scope, channel_ref)
            lines.append(f"• {place}: {reason}")
    if not lines:
        return "Ничего не снято."
    return "\n".join(lines)


def build_confirm_description(
    guild: discord.Guild,
    target: discord.Member,
    records: list[ChannelMute],
) -> str:
    """Ephemeral prompt listing channels/scopes that will be cleared."""
    grouped = group_records_by_channel(records)
    lines = [
        f"У {target.mention} активны ограничения в **{len(grouped)}** каналах.",
        "Снять запреты со всех перечисленных мест?",
        "",
    ]
    for channel_id, channel_records in sorted(grouped.items()):
        channel = guild.get_channel(channel_id)
        channel_ref = (
            channel.mention if isinstance(channel, discord.abc.GuildChannel) else f"<#{channel_id}>"
        )
        removed_scopes = {record.scope for record in channel_records}
        place = scope_place_phrase(
            notification_scope_for_channel(removed_scopes),
            channel_ref,
        )
        lines.append(f"• {place}")
    return "\n".join(lines)


class UnmuteConfirmView(discord.ui.View):
    """Confirm or cancel bulk unmute (ephemeral; moderator-only)."""

    def __init__(
        self,
        service: ChannelMuteService,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        records: list[ChannelMute],
        timeout: float = 60.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._service = service
        self._guild = guild
        self._target = target
        self._moderator = moderator
        self._records = list(records)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._moderator.id:
            await interaction.response.send_message(
                "Подтвердить снятие может только модератор, вызвавший команду.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Снять всё", style=discord.ButtonStyle.success)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._service.unmute_records_batch(
            guild=self._guild,
            target=self._target,
            moderator=self._moderator,
            records=self._records,
        )
        self.stop()
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            logger.warning(
                "Could not delete bulk unmute confirmation message",
                exc_info=True,
            )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.danger)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(
            content="Снятие наказаний отменено.",
            embed=None,
            view=self,
        )

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
