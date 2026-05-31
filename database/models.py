"""Data models for persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ChannelMute:
    """Active or historical channel mute record."""

    id: int | None
    guild_id: int
    channel_id: int
    user_id: int
    moderator_id: int
    reason: str | None
    created_at: datetime
    expire_at: datetime
    overwrite_snapshot: dict[str, Any] | None
