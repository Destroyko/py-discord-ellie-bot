"""Tests for idle trigger logic with media interleaved in discussion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import discord

from modules.media_cleanup.service import should_trigger_cleanup


def _message(
    *,
    created_at: datetime,
    is_media: bool,
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.created_at = created_at
    if is_media:
        message.attachments = [SimpleNamespace()]
        message.embeds = []
    else:
        message.attachments = []
        message.embeds = []
    return message


class TestShouldTriggerCleanup:
    def test_empty_channel(self) -> None:
        now = datetime.now(timezone.utc)
        assert (
            should_trigger_cleanup(
                last_message=None,
                last_text_created_at=None,
                now=now,
                idle_threshold=timedelta(minutes=30),
            )
            is False
        )

    def test_fresh_text_does_not_trigger(self) -> None:
        now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        last = _message(created_at=now - timedelta(minutes=10), is_media=False)
        assert (
            should_trigger_cleanup(
                last_message=last,
                last_text_created_at=last.created_at,
                now=now,
                idle_threshold=timedelta(minutes=30),
            )
            is False
        )

    def test_old_text_triggers(self) -> None:
        now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        last = _message(created_at=now - timedelta(minutes=31), is_media=False)
        assert (
            should_trigger_cleanup(
                last_message=last,
                last_text_created_at=last.created_at,
                now=now,
                idle_threshold=timedelta(minutes=30),
            )
            is True
        )

    def test_recent_media_with_old_text_triggers(self) -> None:
        """GIFs and other media must not reset the idle timer for text cleanup."""
        now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        last_media = _message(created_at=now - timedelta(minutes=2), is_media=True)
        old_text_at = now - timedelta(minutes=45)
        assert (
            should_trigger_cleanup(
                last_message=last_media,
                last_text_created_at=old_text_at,
                now=now,
                idle_threshold=timedelta(minutes=30),
            )
            is True
        )

    def test_recent_media_with_fresh_text_does_not_trigger(self) -> None:
        now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        last_media = _message(created_at=now - timedelta(minutes=2), is_media=True)
        fresh_text_at = now - timedelta(minutes=5)
        assert (
            should_trigger_cleanup(
                last_message=last_media,
                last_text_created_at=fresh_text_at,
                now=now,
                idle_threshold=timedelta(minutes=30),
            )
            is False
        )

    def test_only_media_without_text_does_not_trigger(self) -> None:
        now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        last_media = _message(created_at=now - timedelta(hours=2), is_media=True)
        assert (
            should_trigger_cleanup(
                last_message=last_media,
                last_text_created_at=None,
                now=now,
                idle_threshold=timedelta(minutes=30),
            )
            is False
        )
