"""Result of auto-unmute / unmute_by_id for scheduler coordination."""

from __future__ import annotations

from enum import Enum


class UnmuteOutcome(Enum):
    """What happened when processing a mute record by id."""

    COMPLETED = "completed"
    DELETED_USER = "deleted_user"
    NOT_YET_EXPIRED = "not_yet"
    RECORD_GONE = "record_gone"
    RETRY = "retry"


TERMINAL_UNMUTE_OUTCOMES = frozenset(
    {
        UnmuteOutcome.COMPLETED,
        UnmuteOutcome.DELETED_USER,
        UnmuteOutcome.RECORD_GONE,
    }
)
