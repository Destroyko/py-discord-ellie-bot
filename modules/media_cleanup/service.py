"""Media vs text classification and channel cleanup logic."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord

from modules.media_cleanup.config import MediaCleanupConfig

logger = logging.getLogger("ellie_bot")

_MEDIA_EMBED_TYPES = frozenset({"image", "video", "gifv"})


def is_media_message(message: discord.Message) -> bool:
    """Return True when the message must never be deleted by cleanup."""
    if message.attachments:
        return True
    return any(embed.type in _MEDIA_EMBED_TYPES for embed in message.embeds)


def is_text_message(message: discord.Message) -> bool:
    """Return True when the message is eligible for automatic deletion."""
    return not is_media_message(message)


def should_trigger_cleanup(
    *,
    last_message: discord.Message | None,
    last_text_created_at: datetime | None,
    now: datetime,
    idle_threshold: timedelta,
) -> bool:
    """
    Decide whether idle time has passed and text cleanup should run.

    When the newest message is media (GIF, photo, etc.), recent media does not
    block cleanup: only the age of the newest *text* message matters.
    """
    if last_message is None:
        return False

    if is_text_message(last_message):
        return now - last_message.created_at >= idle_threshold

    if last_text_created_at is None:
        return False

    return now - last_text_created_at >= idle_threshold


async def find_last_text_message(
    channel: discord.TextChannel,
    *,
    limit: int,
) -> discord.Message | None:
    """Return the newest text message in channel history, skipping media."""
    async for message in channel.history(limit=limit):
        if is_text_message(message):
            return message
    return None


async def fetch_channel_activity(
    channel: discord.TextChannel,
    *,
    text_search_limit: int,
) -> tuple[discord.Message | None, discord.Message | None]:
    """
    Return (last_message, last_text_message) for idle checks.

    ``last_text_message`` is None when no text exists within ``text_search_limit``.
    """
    last_message: discord.Message | None = None
    async for message in channel.history(limit=1):
        last_message = message
        break

    if last_message is None:
        return None, None

    if is_text_message(last_message):
        return last_message, last_message

    last_text = await find_last_text_message(channel, limit=text_search_limit)
    return last_message, last_text


async def purge_text_messages(
    channel: discord.TextChannel,
    *,
    purge_limit: int,
) -> list[discord.Message]:
    """
    Delete up to ``purge_limit`` text messages; media messages are preserved.

    discord.py handles bulk vs single deletion for messages older than 14 days.
    """
    return await channel.purge(
        limit=purge_limit,
        check=is_text_message,
        bulk=True,
    )


class MediaCleanupService:
    """Per-channel idle check and phased text purge."""

    def __init__(self, config: MediaCleanupConfig) -> None:
        self._config = config

    @property
    def config(self) -> MediaCleanupConfig:
        return self._config

    async def maybe_cleanup_channel(
        self,
        channel: discord.TextChannel,
    ) -> int | None:
        """
        Purge text when idle threshold is met.

        :returns: number of deleted messages, or None when cleanup was skipped.
        """
        last_message, last_text = await fetch_channel_activity(
            channel,
            text_search_limit=self._config.text_search_limit,
        )
        if last_message is None:
            return None

        idle_threshold = timedelta(minutes=self._config.idle_threshold_minutes)
        now = datetime.now(timezone.utc)
        last_text_at = last_text.created_at if last_text is not None else None

        if not should_trigger_cleanup(
            last_message=last_message,
            last_text_created_at=last_text_at,
            now=now,
            idle_threshold=idle_threshold,
        ):
            return None

        logger.info(
            "Media cleanup starting in #%s (%s)",
            channel.name,
            channel.id,
        )

        try:
            deleted = await purge_text_messages(
                channel,
                purge_limit=self._config.purge_limit,
            )
        except discord.Forbidden:
            logger.warning(
                "Media cleanup forbidden in #%s (%s): missing permissions",
                channel.name,
                channel.id,
            )
            return None
        except discord.HTTPException as exc:
            if exc.status == 429:
                retry_after = getattr(exc, "retry_after", None)
                logger.warning(
                    "Media cleanup rate limited in #%s (%s), retry_after=%s",
                    channel.name,
                    channel.id,
                    retry_after,
                )
            else:
                logger.warning(
                    "Media cleanup HTTP error in #%s (%s): %s",
                    channel.name,
                    channel.id,
                    exc,
                )
            return None

        logger.info(
            "Media cleanup finished in #%s (%s): deleted %s text message(s)",
            channel.name,
            channel.id,
            len(deleted),
        )
        return len(deleted)
