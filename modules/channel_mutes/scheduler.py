"""Asyncio scheduler for automatic mute expiry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord

from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.service import ChannelMuteService, UnmuteSource
from modules.channel_mutes.unmute_outcome import TERMINAL_UNMUTE_OUTCOMES, UnmuteOutcome

logger = logging.getLogger("ellie_bot")

SCHEDULER_INNER_ATTEMPTS = 3
SCHEDULER_MAX_ROUNDS = 3
SCHEDULER_BACKOFF_SECONDS: tuple[int, ...] = (30, 120, 300)


class MuteScheduler:
    """One asyncio task per active mute record."""

    def __init__(self, service: ChannelMuteService, repository: ChannelMuteRepository) -> None:
        self._service = service
        self._repo = repository
        self._tasks: dict[int, asyncio.Task[None]] = {}

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
        """
        Try auto-unmute with inner attempts and backoff between rounds.

        On persistent failure the DB row is kept so Discord deny and record stay
        in sync for manual recovery (no silent delete).
        """
        for round_index in range(SCHEDULER_MAX_ROUNDS):
            for attempt in range(SCHEDULER_INNER_ATTEMPTS):
                outcome, retry_after = await self._try_unmute_once(mute_id, attempt, round_index)

                if outcome in TERMINAL_UNMUTE_OUTCOMES:
                    await self.cancel(mute_id)
                    return
                if outcome == UnmuteOutcome.NOT_YET_EXPIRED:
                    return
                if retry_after is not None and retry_after > 0:
                    await asyncio.sleep(retry_after)

            if round_index < SCHEDULER_MAX_ROUNDS - 1:
                backoff = SCHEDULER_BACKOFF_SECONDS[round_index]
                logger.warning(
                    "Auto-unmute round %s failed for mute %s; backing off %ss",
                    round_index + 1,
                    mute_id,
                    backoff,
                )
                await asyncio.sleep(backoff)

        logger.error(
            "Giving up on auto-unmute for mute %s after %s rounds; keeping DB row",
            mute_id,
            SCHEDULER_MAX_ROUNDS,
        )
        await self.cancel(mute_id)

    async def _try_unmute_once(
        self,
        mute_id: int,
        attempt: int,
        round_index: int,
    ) -> tuple[UnmuteOutcome, float | None]:
        retry_after: float | None = None
        try:
            return (
                await self._service.unmute_by_id(mute_id, source=UnmuteSource.AUTO),
                None,
            )
        except discord.HTTPException as exc:
            if exc.status == 429:
                raw = getattr(exc, "retry_after", None)
                if raw is not None:
                    retry_after = float(raw)
            if exc.status in (403, 404, 429):
                logger.warning(
                    "Auto-unmute round %s attempt %s for mute %s: %s",
                    round_index + 1,
                    attempt + 1,
                    mute_id,
                    exc,
                )
            else:
                logger.exception(
                    "Auto-unmute round %s attempt %s failed for mute %s",
                    round_index + 1,
                    attempt + 1,
                    mute_id,
                )
            return UnmuteOutcome.RETRY, retry_after
        except Exception:
            logger.exception(
                "Auto-unmute round %s attempt %s failed for mute %s",
                round_index + 1,
                attempt + 1,
                mute_id,
            )
            return UnmuteOutcome.RETRY, None
