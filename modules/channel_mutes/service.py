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
from modules.channel_mutes.duration import compute_expire_at, format_duration
from modules.channel_mutes.moderator_notifier import ModeratorNotifier
from modules.channel_mutes.mute_scope import MuteScope, scope_place_phrase
from modules.channel_mutes.overwrite_manager import BitPair, OverwriteManager
from modules.channel_mutes.permissions_bits import (
    deny_flag_value_for_scope,
    empty_scope_snapshot,
    has_full_scope_deny,
    has_scope_deny,
    scope_bit_pairs,
)
from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.unmute_outcome import UnmuteOutcome
from modules.channel_mutes.unmute_plan import (
    UnmuteBatchResult,
    group_records_by_channel,
    notification_scope_for_channel,
)
from modules.channel_mutes.user_presence import UserPresence, resolve_user_presence

logger = logging.getLogger("ellie_bot")

ScheduleCallback = Callable[[int, datetime], Awaitable[None]]
CancelCallback = Callable[[int], Awaitable[None]]


class UnmuteSource(Enum):
    """Origin of an unmute operation."""

    MANUAL = "manual"
    AUTO = "auto"


class ChannelMuteService:
    """Mute, extend, and unmute users in text channels (chat and/or threads)."""

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
        scope: MuteScope = MuteScope.CHAT_ONLY,
    ) -> tuple[ChannelMute, bool]:
        """
        Apply or extend a channel mute for the given scope.

        ``channel`` is the channel whose overwrites are edited (the parent text
        channel when the moderator targeted a thread).

        :returns: (mute record, was_extended)
        """
        expire_at = compute_expire_at(duration_delta)
        now = datetime.now(timezone.utc)
        existing = self._repo.get_by_keys(guild.id, channel.id, target.id, scope)

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
                scope=scope,
            )

        overwrite = channel.overwrites_for(target)
        adopted = has_scope_deny(overwrite, scope)
        if adopted:
            snapshot = empty_scope_snapshot(scope)
        else:
            snapshot = self._capture_snapshot(guild.id, channel, target, scope)

        discord_modified = not (adopted and has_full_scope_deny(overwrite, scope))
        if discord_modified:
            try:
                await self._overwrite.apply_mute(channel, target, scope)
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
            scope=scope,
        )

        try:
            saved = self._repo.insert(mute)
            assert saved.id is not None
            if self._on_scheduled:
                await self._on_scheduled(saved.id, saved.expire_at)
        except Exception:
            if discord_modified:
                await self._rollback_overwrite(guild.id, channel, target, snapshot, scope)
            raise

        await self._dm.send_mute_issued(
            target,
            guild_name=guild.name,
            guild_id=guild.id,
            channel_name=channel.name,
            channel_id=channel.id,
            expire_at=expire_at,
            duration_text=duration_text,
            reason=reason,
            scope=scope,
        )
        await self._moderator_notifier.send_mute_notice(
            guild,
            moderator=moderator,
            target=target,
            channel=channel,
            duration_text=duration_text,
            reason=reason,
            scope=scope,
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
            scope=scope,
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
        scope: MuteScope,
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

        assert updated.id is not None

        if self._on_cancelled:
            await self._on_cancelled(existing.id)
        if self._on_scheduled:
            await self._on_scheduled(updated.id, updated.expire_at)

        previous_duration_text = format_duration(existing.expire_at - existing.created_at)

        await self._dm.send_mute_issued(
            target,
            guild_name=guild.name,
            guild_id=guild.id,
            channel_name=channel.name,
            channel_id=channel.id,
            expire_at=expire_at,
            duration_text=duration_text,
            reason=reason,
            is_extended=True,
            scope=scope,
        )
        await self._moderator_notifier.send_mute_notice(
            guild,
            moderator=moderator,
            target=target,
            channel=channel,
            duration_text=duration_text,
            reason=reason,
            previous_duration_text=previous_duration_text,
            is_extended=True,
            scope=scope,
        )
        await self._audit.log_action(
            AuditAction.EXTENDED,
            guild=guild,
            channel=channel,
            target=target,
            moderator=moderator,
            previous_duration_text=previous_duration_text,
            previous_expire_at=existing.expire_at,
            expire_at=expire_at,
            duration_text=duration_text,
            reason=reason,
            scope=scope,
        )
        return updated, True

    async def unmute_channel(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        target: discord.Member,
        moderator: discord.Member | None,
        scope: MuteScope = MuteScope.CHAT_ONLY,
        source: UnmuteSource = UnmuteSource.MANUAL,
    ) -> bool:
        """
        Remove a channel mute for the given scope idempotently.

        :returns: True if a mute was active and removed.
        """
        existing = self._repo.get_by_keys(guild.id, channel.id, target.id, scope)
        if existing is None:
            return False

        removed = await self._unmute_record_core(
            guild,
            existing,
            target,
            source=source,
            moderator=moderator,
        )
        if not removed:
            return False

        if source == UnmuteSource.MANUAL and moderator is not None:
            await self._dm.send_unmute(
                target,
                guild_name=guild.name,
                guild_id=guild.id,
                channel_name=channel.name,
                channel_id=channel.id,
                scope=scope,
            )
            await self._moderator_notifier.send_unmute_notice(
                guild,
                moderator=moderator,
                target=target,
                places=[scope_place_phrase(scope, channel.mention)],
            )

        return True

    async def unmute_records_batch(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        records: list[ChannelMute],
    ) -> UnmuteBatchResult:
        """
        Remove multiple mute records; grouped DM/mod notice per channel.

        Continues on per-record failure; audit is one entry per removed record.
        """
        succeeded: list[ChannelMute] = []
        failed: list[tuple[ChannelMute, str]] = []

        for record in records:
            try:
                removed = await self._unmute_record_core(
                    guild,
                    record,
                    target,
                    source=UnmuteSource.MANUAL,
                    moderator=moderator,
                )
                if removed:
                    succeeded.append(record)
                else:
                    failed.append((record, "запись не найдена"))
            except DiscordActionError as exc:
                failed.append((record, str(exc)))
            except Exception as exc:
                logger.exception("Batch unmute failed for record %s", record.id)
                failed.append((record, str(exc)))

        if succeeded:
            await self._send_batch_unmute_notifications(
                guild, target, moderator, succeeded
            )

        return UnmuteBatchResult(succeeded=succeeded, failed=failed)

    async def _send_batch_unmute_notifications(
        self,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        succeeded: list[ChannelMute],
    ) -> None:
        grouped = group_records_by_channel(succeeded)
        places: list[str] = []

        for channel_id, channel_records in sorted(grouped.items()):
            channel = await self._resolve_text_channel(guild, channel_id)
            channel_name = channel.name if channel is not None else str(channel_id)
            channel_ref = (
                channel.mention if channel is not None else f"<#{channel_id}>"
            )
            removed_scopes = {record.scope for record in channel_records}
            notify_scope = notification_scope_for_channel(removed_scopes)
            places.append(scope_place_phrase(notify_scope, channel_ref))
            await self._dm.send_unmute(
                target,
                guild_name=guild.name,
                guild_id=guild.id,
                channel_name=channel_name,
                channel_id=channel_id,
                scope=notify_scope,
            )

        await self._moderator_notifier.send_unmute_notice(
            guild,
            moderator=moderator,
            target=target,
            places=places,
        )

    async def _unmute_record_core(
        self,
        guild: discord.Guild,
        record: ChannelMute,
        target: discord.Member,
        *,
        source: UnmuteSource,
        moderator: discord.Member | None = None,
    ) -> bool:
        """Remove one DB record and sync Discord. Audit per record when manual."""
        channel = await self._resolve_text_channel(guild, record.channel_id)
        if channel is None:
            await self._drop_unavailable_record(record, guild, target, moderator, source)
            return True

        scope = record.scope
        existing = self._repo.get_by_keys(
            guild.id, channel.id, target.id, scope
        )
        if existing is None:
            return False

        overwrite = channel.overwrites_for(target)

        if not has_scope_deny(overwrite, scope):
            self._repo.delete(existing.id)
            if self._on_cancelled and existing.id:
                await self._on_cancelled(existing.id)
            await self._log_unmute_audit(
                guild,
                channel,
                target,
                scope,
                source=source,
                moderator=moderator,
            )
            return True

        snapshot = existing.overwrite_snapshot
        pairs = self._revert_pairs(guild.id, channel.id, target.id, scope)
        try:
            if pairs:
                await self._overwrite.revert_mute(channel, target, snapshot, pairs)
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
                await self._overwrite.apply_mute(channel, target, scope)
            except discord.HTTPException:
                logger.exception("Failed to re-apply mute after DB failure")
            raise

        await self._log_unmute_audit(
            guild,
            channel,
            target,
            scope,
            source=source,
            moderator=moderator,
        )
        return True

    async def _drop_unavailable_record(
        self,
        record: ChannelMute,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member | None,
        source: UnmuteSource,
    ) -> None:
        """Channel gone — remove DB row; overwrite not reachable."""
        assert record.id is not None
        self._repo.delete(record.id)
        if self._on_cancelled:
            await self._on_cancelled(record.id)
        await self._audit.log_action(
            AuditAction.AUTO_UNMUTED if source == UnmuteSource.AUTO else AuditAction.UNMUTED,
            guild=guild,
            channel=None,
            target=target if source == UnmuteSource.MANUAL else None,
            moderator=moderator,
            target_user_id=record.user_id,
            channel_id=record.channel_id,
            scope=record.scope,
        )

    async def _log_unmute_audit(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        target: discord.Member,
        scope: MuteScope,
        *,
        source: UnmuteSource,
        moderator: discord.Member | None,
    ) -> None:
        if source == UnmuteSource.MANUAL and moderator is not None:
            await self._audit.log_action(
                AuditAction.UNMUTED,
                guild=guild,
                channel=channel,
                target=target,
                moderator=moderator,
                scope=scope,
            )
        elif source == UnmuteSource.AUTO:
            await self._audit.log_action(
                AuditAction.AUTO_UNMUTED,
                guild=guild,
                channel=channel,
                target=target,
                target_user_id=target.id,
                channel_id=channel.id,
                scope=scope,
            )

    async def unmute_by_id(
        self,
        mute_id: int,
        *,
        source: UnmuteSource = UnmuteSource.AUTO,
    ) -> UnmuteOutcome:
        """Unmute using database record (scheduler / startup)."""
        record = self._repo.get_by_id(mute_id)
        if record is None:
            return UnmuteOutcome.RECORD_GONE

        guild = await self._resolve_guild(record.guild_id)
        if guild is None:
            return UnmuteOutcome.RETRY

        channel = await self._resolve_text_channel(guild, record.channel_id)
        if channel is None:
            return await self._finalize_channel_unavailable(record, guild)

        presence, member = await resolve_user_presence(self._bot, guild, record.user_id)

        if presence == UserPresence.DELETED:
            return await self._cleanup_deleted_user(record, channel)

        now = datetime.now(timezone.utc)
        if presence == UserPresence.LEFT_GUILD:
            if now < record.expire_at:
                return UnmuteOutcome.NOT_YET_EXPIRED
            return await self._finalize_auto_unmute(record, guild, channel, member=None)

        assert member is not None
        try:
            await self.unmute_channel(
                guild=guild,
                channel=channel,
                target=member,
                moderator=None,
                scope=record.scope,
                source=source,
            )
        except (DiscordActionError, discord.HTTPException):
            logger.exception("Auto-unmute failed for mute %s (member on guild)", mute_id)
            return UnmuteOutcome.RETRY

        if self._repo.get_by_id(mute_id) is None:
            return UnmuteOutcome.COMPLETED
        return UnmuteOutcome.RETRY

    async def _resolve_guild(self, guild_id: int) -> discord.Guild | None:
        guild = self._bot.get_guild(guild_id)
        if guild is not None:
            return guild
        try:
            fetched = await self._bot.fetch_guild(guild_id)
            return fetched
        except discord.HTTPException:
            logger.warning("Could not fetch guild %s for auto-unmute", guild_id)
            return None

    async def _resolve_text_channel(
        self,
        guild: discord.Guild,
        channel_id: int,
    ) -> discord.TextChannel | None:
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        try:
            fetched = await guild.fetch_channel(channel_id)
        except discord.HTTPException:
            logger.warning(
                "Could not fetch channel %s in guild %s for auto-unmute",
                channel_id,
                guild.id,
            )
            return None
        if isinstance(fetched, discord.TextChannel):
            return fetched
        return None

    async def _finalize_channel_unavailable(
        self,
        record: ChannelMute,
        guild: discord.Guild,
    ) -> UnmuteOutcome:
        """Channel deleted or not text — drop DB record; overwrite not reachable."""
        assert record.id is not None
        self._repo.delete(record.id)
        if self._on_cancelled:
            await self._on_cancelled(record.id)
        await self._audit.log_action(
            AuditAction.AUTO_UNMUTED,
            guild=guild,
            channel=None,
            target=None,
            target_user_id=record.user_id,
            channel_id=record.channel_id,
            scope=record.scope,
        )
        return UnmuteOutcome.COMPLETED

    async def _finalize_auto_unmute(
        self,
        record: ChannelMute,
        guild: discord.Guild,
        channel: discord.TextChannel,
        *,
        member: discord.Member | None,
    ) -> UnmuteOutcome:
        """Revert overwrite and remove DB row (member on guild or left)."""
        assert record.id is not None
        user_id = record.user_id
        lookup: discord.Member | discord.Object = (
            member if member is not None else discord.Object(id=user_id)
        )
        overwrite = channel.overwrites_for(lookup)
        snapshot = record.overwrite_snapshot

        if not has_scope_deny(overwrite, record.scope):
            self._repo.delete(record.id)
            if self._on_cancelled:
                await self._on_cancelled(record.id)
            await self._audit.log_action(
                AuditAction.AUTO_UNMUTED,
                guild=guild,
                channel=channel,
                target=member,
                target_user_id=user_id,
                channel_id=channel.id,
                scope=record.scope,
            )
            return UnmuteOutcome.COMPLETED

        pairs = self._revert_pairs(guild.id, channel.id, user_id, record.scope)
        try:
            if pairs:
                if member is not None:
                    await self._overwrite.revert_mute(channel, member, snapshot, pairs)
                else:
                    await self._overwrite.revert_mute_by_user_id(
                        channel, user_id, snapshot, pairs, member=None
                    )
        except discord.HTTPException:
            logger.exception(
                "Failed to revert overwrite for mute %s user %s channel %s",
                record.id,
                user_id,
                channel.id,
            )
            return UnmuteOutcome.RETRY

        try:
            self._repo.delete(record.id)
            if self._on_cancelled:
                await self._on_cancelled(record.id)
        except Exception:
            logger.exception("DB delete failed after Discord revert for mute %s", record.id)
            if member is not None:
                try:
                    await self._overwrite.apply_mute(channel, member, record.scope)
                except discord.HTTPException:
                    logger.exception("Failed to re-apply mute after DB failure")
            return UnmuteOutcome.RETRY

        await self._audit.log_action(
            AuditAction.AUTO_UNMUTED,
            guild=guild,
            channel=channel,
            target=member,
            target_user_id=user_id,
            channel_id=channel.id,
            scope=record.scope,
        )
        return UnmuteOutcome.COMPLETED

    async def _cleanup_deleted_user(
        self,
        record: ChannelMute,
        channel: discord.TextChannel,
    ) -> UnmuteOutcome:
        """Remove DB row for deleted account; best-effort revert without audit."""
        assert record.id is not None
        overwrite = channel.overwrites_for(discord.Object(id=record.user_id))
        if has_scope_deny(overwrite, record.scope):
            pairs = self._revert_pairs(
                record.guild_id, channel.id, record.user_id, record.scope
            )
            if pairs:
                try:
                    await self._overwrite.revert_mute_by_user_id(
                        channel,
                        record.user_id,
                        record.overwrite_snapshot,
                        pairs,
                        member=None,
                    )
                except discord.HTTPException:
                    logger.warning(
                        "Best-effort revert for deleted user %s in channel %s failed",
                        record.user_id,
                        channel.id,
                    )

        self._repo.delete(record.id)
        if self._on_cancelled:
            await self._on_cancelled(record.id)
        logger.info(
            "Removed mute record %s for deleted user %s",
            record.id,
            record.user_id,
        )
        return UnmuteOutcome.DELETED_USER

    def _capture_snapshot(
        self,
        guild_id: int,
        channel: discord.TextChannel,
        target: discord.Member,
        scope: MuteScope,
    ) -> dict[str, Any]:
        """
        Capture prior tri-state of the scope's bits.

        For bits already managed by a sibling mute record in this channel, the
        sibling's original prior state is propagated so the true pre-mute value
        is restored only when the last record managing the bit is removed.
        """
        state = self._overwrite.read_scope_state(channel, target, scope)
        for record in self._repo.list_for_user_in_channel(
            guild_id, channel.id, target.id
        ):
            if record.scope == scope or record.overwrite_snapshot is None:
                continue
            for key, value in record.overwrite_snapshot.items():
                if key in state:
                    state[key] = value
        return state

    def _still_needed_bits(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        exclude_scope: MuteScope,
    ) -> int:
        """Bitmask of deny bits still required by other active records."""
        value = 0
        for record in self._repo.list_for_user_in_channel(
            guild_id, channel_id, user_id
        ):
            if record.scope == exclude_scope:
                continue
            value |= deny_flag_value_for_scope(record.scope)
        return value

    def _revert_pairs(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        scope: MuteScope,
    ) -> list[BitPair]:
        """Bit pairs to revert for ``scope``, excluding bits other records need."""
        keep = self._still_needed_bits(guild_id, channel_id, user_id, scope)
        return [pair for pair in scope_bit_pairs(scope) if not (pair[1] & keep)]

    async def _rollback_overwrite(
        self,
        guild_id: int,
        channel: discord.TextChannel,
        target: discord.Member,
        snapshot: dict[str, Any] | None,
        scope: MuteScope,
    ) -> None:
        pairs = self._revert_pairs(guild_id, channel.id, target.id, scope)
        if pairs:
            await self._overwrite.rollback_after_failed_db(
                channel, target, snapshot, pairs
            )
