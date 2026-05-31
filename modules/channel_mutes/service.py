"""Channel mute business logic."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import discord

from core.config_loader import AppConfig
from core.exceptions import DiscordActionError, ValidationError
from database.models import ChannelMute
from modules.channel_mutes.audit_log import AuditAction, AuditLog
from modules.channel_mutes.dm_notifier import DmNotifier
from modules.channel_mutes.duration import compute_expire_at
from modules.channel_mutes.moderator_notifier import ModeratorNotifier
from modules.channel_mutes.overwrite_manager import OverwriteManager
from modules.channel_mutes.permissions_bits import SEND_MESSAGES_BIT
from modules.channel_mutes.repository import ChannelMuteRepository

logger = logging.getLogger("ellie_bot")

ScheduleCallback = Callable[[int, datetime], Awaitable[None]]
CancelCallback = Callable[[int], Awaitable[None]]


class UnmuteSource(Enum):
    """Origin of an unmute operation."""

    MANUAL = "manual"
    AUTO = "auto"


class ChannelMuteService:
    """Mute, extend, and unmute users in text channels."""

    def __init__(
        self,
        bot: discord.Client,
        config: AppConfig,
        repository: ChannelMuteRepository,
        overwrite_manager: OverwriteManager | None = None,
        dm_notifier: DmNotifier | None = None,
        moderator_notifier: ModeratorNotifier | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._bot = bot
        self._config = config
        self._repo = repository
        self._overwrite = overwrite_manager or OverwriteManager()
        self._dm = dm_notifier or DmNotifier()
        self._moderator_notifier = moderator_notifier or ModeratorNotifier(config)
        self._audit = audit_log or AuditLog(bot, config)
        self._on_scheduled: ScheduleCallback | None = None
        self._on_cancelled: CancelCallback | None = None

    def set_scheduler_hooks(
        self,
        on_scheduled: ScheduleCallback,
        on_cancelled: CancelCallback,
    ) -> None:
        """Inject scheduler schedule/cancel callbacks."""
        self._on_scheduled = on_scheduled
        self._on_cancelled = on_cancelled

    async def mute_channel(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        target: discord.Member,
        moderator: discord.Member,
        duration_delta: Any,
        duration_text: str,
        reason: str | None,
    ) -> tuple[ChannelMute, bool]:
        """
        Apply or extend a channel mute.

        :returns: (mute record, was_extended)
        """
        expire_at = compute_expire_at(duration_delta)
        now = datetime.now(timezone.utc)
        existing = self._repo.get_by_keys(guild.id, channel.id, target.id)

        if existing is not None:
            return await self._extend_mute(
                existing=existing,
                guild=guild,
                channel=channel,
                target=target,
                moderator=moderator,
                expire_at=expire_at,
                duration_text=duration_text,
                reason=reason,
                now=now,
            )

        snapshot = await self._overwrite.capture_snapshot(channel, target)
        try:
            await self._overwrite.apply_mute(channel, target)
        except discord.HTTPException as exc:
            raise DiscordActionError(
                f"Не могу выдать наказание: {exc.text if hasattr(exc, 'text') else exc}"
            ) from exc

        mute = ChannelMute(
            id=None,
            guild_id=guild.id,
            channel_id=channel.id,
            user_id=target.id,
            moderator_id=moderator.id,
            reason=reason,
            created_at=now,
            expire_at=expire_at,
            overwrite_snapshot=snapshot,
        )

        try:
            saved = self._repo.insert(mute)
            if self._on_scheduled:
                await self._on_scheduled(saved.id, saved.expire_at)
        except Exception:
            await self._overwrite.rollback_after_failed_db(channel, target, snapshot)
            raise

        await self._dm.send_mute_issued(
            target,
            guild_name=guild.name,
            channel_name=channel.name,
            expire_at=expire_at,
            duration_text=duration_text,
            reason=reason,
        )
        await self._moderator_notifier.send_mute_notice(
            guild,
            target=target,
            channel=channel,
            duration_text=duration_text,
            reason=reason,
        )
        await self._audit.log_action(
            AuditAction.MUTED,
            guild=guild,
            channel=channel,
            target=target,
            moderator=moderator,
            expire_at=expire_at,
            duration_text=duration_text,
            reason=reason,
        )
        return saved, False

    async def _extend_mute(
        self,
        *,
        existing: ChannelMute,
        guild: discord.Guild,
        channel: discord.TextChannel,
        target: discord.Member,
        moderator: discord.Member,
        expire_at: datetime,
        duration_text: str,
        reason: str | None,
        now: datetime,
    ) -> tuple[ChannelMute, bool]:
        assert existing.id is not None
        updated = self._repo.update_extend(
            existing.id,
            expire_at=expire_at,
            moderator_id=moderator.id,
            reason=reason,
            created_at=now,
        )
        if updated is None:
            raise ValidationError("Не удалось обновить наказание.")

        if self._on_cancelled:
            await self._on_cancelled(existing.id)
        if self._on_scheduled:
            await self._on_scheduled(updated.id, updated.expire_at)

        await self._dm.send_mute_issued(
            target,
            guild_name=guild.name,
            channel_name=channel.name,
            expire_at=expire_at,
            duration_text=duration_text,
            reason=reason,
        )
        await self._moderator_notifier.send_mute_notice(
            guild,
            target=target,
            channel=channel,
            duration_text=duration_text,
            reason=reason,
        )
        await self._audit.log_action(
            AuditAction.EXTENDED,
            guild=guild,
            channel=channel,
            target=target,
            moderator=moderator,
            expire_at=expire_at,
            duration_text=duration_text,
            reason=reason,
        )
        return updated, True

    async def unmute_channel(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        target: discord.Member,
        moderator: discord.Member | None,
        source: UnmuteSource = UnmuteSource.MANUAL,
    ) -> bool:
        """
        Remove channel mute idempotently.

        :returns: True if a mute was active and removed.
        """
        existing = self._repo.get_by_keys(guild.id, channel.id, target.id)
        overwrite = channel.overwrites_for(target)

        if existing is None:
            return False

        # DB record exists; sync Discord (6.2: no overwrite -> clean DB, treat as unmuted)
        if not self._has_send_deny(overwrite):
            self._repo.delete(existing.id)
            if self._on_cancelled and existing.id:
                await self._on_cancelled(existing.id)
            return source == UnmuteSource.MANUAL

        snapshot = existing.overwrite_snapshot
        try:
            await self._overwrite.revert_mute(channel, target, snapshot)
        except discord.HTTPException as exc:
            raise DiscordActionError(
                f"Не удалось снять наказание: {exc.text if hasattr(exc, 'text') else exc}"
            ) from exc

        try:
            self._repo.delete(existing.id)
            if self._on_cancelled and existing.id:
                await self._on_cancelled(existing.id)
        except Exception:
            try:
                await self._overwrite.apply_mute(channel, target)
            except discord.HTTPException:
                logger.exception("Failed to re-apply mute after DB failure")
            raise

        if source == UnmuteSource.MANUAL and moderator is not None:
            await self._dm.send_unmute(
                target,
                guild_name=guild.name,
                channel_name=channel.name,
            )
            await self._audit.log_action(
                AuditAction.UNMUTED,
                guild=guild,
                channel=channel,
                target=target,
                moderator=moderator,
            )
        elif source == UnmuteSource.AUTO:
            await self._audit.log_action(
                AuditAction.AUTO_UNMUTED,
                guild=guild,
                channel=channel,
                target=target,
                target_user_id=target.id,
                channel_id=channel.id,
            )

        return True

    async def unmute_by_id(
        self,
        mute_id: int,
        *,
        source: UnmuteSource = UnmuteSource.AUTO,
    ) -> None:
        """Unmute using database record (scheduler / startup)."""
        record = self._repo.get_by_id(mute_id)
        if record is None:
            return

        guild = self._bot.get_guild(record.guild_id)
        if guild is None:
            self._repo.delete(mute_id)
            return

        channel = guild.get_channel(record.channel_id)
        if not isinstance(channel, discord.TextChannel):
            self._repo.delete(mute_id)
            await self._audit.log_action(
                AuditAction.AUTO_UNMUTED,
                guild=guild,
                channel=None,
                target=None,
                target_user_id=record.user_id,
                channel_id=record.channel_id,
            )
            return

        member = guild.get_member(record.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(record.user_id)
            except discord.NotFound:
                self._repo.delete(mute_id)
                await self._audit.log_action(
                    AuditAction.AUTO_UNMUTED,
                    guild=guild,
                    channel=channel,
                    target=None,
                    target_user_id=record.user_id,
                    channel_id=record.channel_id,
                )
                return

        await self.unmute_channel(
            guild=guild,
            channel=channel,
            target=member,
            moderator=None,
            source=source,
        )

    @staticmethod
    def _has_send_deny(overwrite: discord.PermissionOverwrite) -> bool:
        _allow, deny = overwrite.pair()
        return bool(deny.value & SEND_MESSAGES_BIT)
