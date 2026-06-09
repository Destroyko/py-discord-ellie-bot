"""Tests for guild-wide mention GIF cooldown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from database.database import Database
from modules.mention_gif.cooldown import GuildCooldownTracker
from modules.mention_gif.cooldown_repository import MentionGifCooldownRepository


@pytest.fixture
def cooldown_tracker(tmp_path: Path) -> GuildCooldownTracker:
    db = Database(tmp_path / "cooldown.db")
    db.init_db()
    repo = MentionGifCooldownRepository(db)
    tracker = GuildCooldownTracker(repo, cooldown_seconds=600)
    yield tracker
    db.close()


class TestGuildCooldownTracker:
    def test_allows_first_send(self, cooldown_tracker: GuildCooldownTracker) -> None:
        assert cooldown_tracker.can_send(100) is True

    def test_blocks_within_cooldown(self, cooldown_tracker: GuildCooldownTracker) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        cooldown_tracker.mark_sent(100, sent_at=now)
        assert cooldown_tracker.can_send(100, now=now + timedelta(minutes=5)) is False

    def test_allows_after_cooldown(self, cooldown_tracker: GuildCooldownTracker) -> None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        cooldown_tracker.mark_sent(100, sent_at=now)
        assert cooldown_tracker.can_send(100, now=now + timedelta(minutes=10)) is True

    def test_persists_across_tracker_instances(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "persist.db")
        db.init_db()
        sent_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        GuildCooldownTracker(
            MentionGifCooldownRepository(db), cooldown_seconds=600
        ).mark_sent(100, sent_at=sent_at)

        tracker = GuildCooldownTracker(
            MentionGifCooldownRepository(db), cooldown_seconds=600
        )
        assert tracker.can_send(100, now=sent_at + timedelta(minutes=1)) is False
        db.close()
