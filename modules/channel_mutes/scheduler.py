"""Asyncio scheduler for automatic mute expiry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord

from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.service import ChannelMuteService, UnmuteSource

logger = logging.getLogger("ellie_bot")

SCHEDULER_MAX_RETRIES = 3


class MuteScheduler:
    """One asyncio task per active mute record."""

    def __init__(self, service: ChannelMuteService, repository: ChannelMuteRepository) -> None:
        self._service = service
        self._repo = repository
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._retry_counts: dict[int, int] = {}

    async def schedule(self, mute_id: int, expire_at: datetime) -> None:
        """Schedule automatic unmute at expire_at."""
        await self.cancel(mute_id)
        self._tasks[mute_id] = asyncio.create_task(
            self._run_timer(mute_id, expire_at),
            name=f"mute-expire-{mute_id}",
        )

    async def cancel(self, mute_id: int) -> None:
        """Cancel a pending unmute task."""
        task = self._tasks.pop(mute_id, None)
        self._retry_counts.pop(mute_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def restore_all(self, guild_id: int) -> None:
        """Reschedule active mutes and process expired ones on startup."""
        expired = self._repo.list_expired(guild_id)
        for mute in expired:
            if mute.id is not None:
                await self._expire_with_retries(mute.id)

        active = self._repo.list_all_active(guild_id)
        now = datetime.now(timezone.utc)
        for mute in active:
            if mute.id is None:
                continue
            if mute.expire_at <= now:
                await self._expire_with_retries(mute.id)
            else:
                await self.schedule(mute.id, mute.expire_at)

    async def _run_timer(self, mute_id: int, expire_at: datetime) -> None:
        now = datetime.now(timezone.utc)
        delay = (expire_at - now).total_seconds()
        if delay > 0:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

        await self._expire_with_retries(mute_id)

    async def _expire_with_retries(self, mute_id: int) -> None:
        for attempt in range(SCHEDULER_MAX_RETRIES):
            try:
                await self._service.unmute_by_id(mute_id, source=UnmuteSource.AUTO)
                await self.cancel(mute_id)
                return
            except discord.HTTPException as exc:
                if exc.status in (403, 404):
                    logger.warning(
                        "Auto-unmute attempt %s for mute %s: %s",
                        attempt + 1,
                        mute_id,
                        exc,
                    )
                else:
                    logger.exception("Auto-unmute failed for mute %s", mute_id)
            except Exception:
                logger.exception("Auto-unmute failed for mute %s", mute_id)

        count = self._retry_counts.get(mute_id, 0) + 1
        self._retry_counts[mute_id] = count
        if count >= SCHEDULER_MAX_RETRIES:
            logger.error("Giving up on mute %s after %s retries; removing DB row", mute_id, count)
            self._repo.delete(mute_id)
            await self.cancel(mute_id)
