"""Mute scope model: chat, threads, or both (no discord.py imports)."""

from __future__ import annotations

from enum import Enum

from core.exceptions import ValidationError


class MuteScope(Enum):
    """What a channel mute restricts for the target member."""

    CHAT_ONLY = "chat_only"
    THREADS_ONLY = "threads_only"
    CHAT_AND_THREADS = "chat_and_threads"

    @property
    def affects_chat(self) -> bool:
        """Whether this scope denies sending in the parent text channel."""
        return self in (MuteScope.CHAT_ONLY, MuteScope.CHAT_AND_THREADS)

    @property
    def affects_threads(self) -> bool:
        """Whether this scope denies sending in the channel's threads."""
        return self in (MuteScope.THREADS_ONLY, MuteScope.CHAT_AND_THREADS)


# Command-level option values (what the moderator picks).
COMMAND_SCOPE_CHAT = "chat"
COMMAND_SCOPE_THREADS = "threads"
COMMAND_SCOPE_ALL = "all"

COMMAND_SCOPE_VALUES = (
    COMMAND_SCOPE_CHAT,
    COMMAND_SCOPE_THREADS,
    COMMAND_SCOPE_ALL,
)

_COMMAND_TO_SCOPE = {
    COMMAND_SCOPE_CHAT: MuteScope.CHAT_ONLY,
    COMMAND_SCOPE_THREADS: MuteScope.THREADS_ONLY,
    COMMAND_SCOPE_ALL: MuteScope.CHAT_AND_THREADS,
}


def scope_from_command_value(value: str) -> MuteScope:
    """
    Map a command option value (chat/threads/all) to a :class:`MuteScope`.

    :raises ValidationError: on an unknown value.
    """
    try:
        return _COMMAND_TO_SCOPE[value]
    except KeyError as exc:
        raise ValidationError("Неизвестное значение параметра scope.") from exc


def scope_from_stored_value(value: str) -> MuteScope:
    """Map a stored DB string to a :class:`MuteScope` (fallback: chat_only)."""
    try:
        return MuteScope(value)
    except ValueError:
        return MuteScope.CHAT_ONLY


def scope_place_phrase(scope: MuteScope, channel_ref: str) -> str:
    """
    Build a locative Russian phrase for where the restriction applies.

    ``channel_ref`` is an already-formatted reference (mention, link, or name).
    Examples: "в чате #general", "в ветках чата #general",
    "в чате #general и его ветках".
    """
    if scope is MuteScope.CHAT_ONLY:
        return f"в чате {channel_ref}"
    if scope is MuteScope.THREADS_ONLY:
        return f"в ветках чата {channel_ref}"
    return f"в чате {channel_ref} и его ветках"
