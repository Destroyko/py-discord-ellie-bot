"""Permission bits and snapshot encoding for channel overwrites."""

from __future__ import annotations

from typing import Any

import discord

# Extend this list to deny additional permission flags with the same command later.
# Note: use flag attributes without () — send_messages is not callable in discord.py 2.x.
SEND_MESSAGES_FLAG = discord.Permissions.send_messages
# Bitmask for bitwise ops on PermissionOverwrite pair() values (flag_value uses .flag, not .value).
SEND_MESSAGES_BIT: int = SEND_MESSAGES_FLAG.flag
PERMISSIONS_TO_DENY: tuple[Any, ...] = (SEND_MESSAGES_FLAG,)


def combined_deny_flag_value() -> int:
    """Bitmask of all permission flags the bot denies on mute."""
    value = 0
    for flag in PERMISSIONS_TO_DENY:
        value |= flag.flag
    return value


SNAPSHOT_KEY_SEND_MESSAGES = "send_messages"


def capture_send_messages_state(
    overwrite: discord.PermissionOverwrite | None,
) -> dict[str, Any] | None:
    """
    Capture send_messages tri-state before applying mute.

    Values: true (allow), false (deny), null (inherit / no explicit bit).
    """
    if overwrite is None:
        return {SNAPSHOT_KEY_SEND_MESSAGES: None}

    allow, deny = overwrite.pair()
    if allow.value & SEND_MESSAGES_BIT:
        return {SNAPSHOT_KEY_SEND_MESSAGES: True}
    if deny.value & SEND_MESSAGES_BIT:
        return {SNAPSHOT_KEY_SEND_MESSAGES: False}
    return {SNAPSHOT_KEY_SEND_MESSAGES: None}


def snapshot_from_json(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate snapshot dict from database."""
    if data is None:
        return None
    return dict(data)


def has_our_send_messages_deny(overwrite: discord.PermissionOverwrite | None) -> bool:
    """Return True if overwrite explicitly denies send_messages."""
    if overwrite is None:
        return False
    _allow, deny = overwrite.pair()
    return bool(deny.value & SEND_MESSAGES_BIT)


def compute_reverted_send_messages_pair(
    allow: discord.Permissions,
    deny: discord.Permissions,
    snapshot: dict[str, Any] | None,
) -> tuple[discord.Permissions, discord.Permissions]:
    """
    Remove bot send_messages deny and restore prior send_messages state from snapshot.

    Shared by revert_mute (Member) and revert_mute_by_user_id (left guild).
    """
    new_deny_value = deny.value & ~SEND_MESSAGES_BIT
    prior = None if snapshot is None else snapshot.get(SNAPSHOT_KEY_SEND_MESSAGES)

    if prior is True:
        new_allow_value = allow.value | SEND_MESSAGES_BIT
        new_deny_value = new_deny_value & ~SEND_MESSAGES_BIT
    elif prior is False:
        new_allow_value = allow.value & ~SEND_MESSAGES_BIT
        new_deny_value = new_deny_value | SEND_MESSAGES_BIT
    else:
        new_allow_value = allow.value & ~SEND_MESSAGES_BIT
        new_deny_value = new_deny_value & ~SEND_MESSAGES_BIT

    return (
        discord.Permissions(new_allow_value),
        discord.Permissions(new_deny_value),
    )
