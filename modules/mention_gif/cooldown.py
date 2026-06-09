"""Guild-wide cooldown checks for mention GIF replies."""

from __future__ import annotations

from datetime import datetime, timezone

from modules.mention_gif.cooldown_repository import MentionGifCooldownRepository


class GuildCooldownTracker:
    """Enforce a server-wide minimum interval between mention GIF replies."""

    def __init__(
        self,
        repository: MentionGifCooldownRepository,
        cooldown_seconds: int,
    ) -> None:
        self._repo = repository
        self._cooldown_seconds = cooldown_seconds

    def can_send(self, guild_id: int, *, now: datetime | None = None) -> bool:
        """Return True if the cooldown has elapsed since the last reply."""
        last_sent = self._repo.get_last_sent_at(guild_id)
        if last_sent is None:
            return True
        current = now or datetime.now(timezone.utc)
        elapsed = (current - last_sent).total_seconds()
        return elapsed >= self._cooldown_seconds

    def mark_sent(self, guild_id: int, *, sent_at: datetime | None = None) -> None:
        """Persist the time of a successful reply."""
        self._repo.set_last_sent_at(guild_id, sent_at or datetime.now(timezone.utc))
