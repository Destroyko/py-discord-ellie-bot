"""Permission bits and snapshot encoding for channel overwrites."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import discord

from modules.channel_mutes.mute_scope import MuteScope

# Note: use flag attributes without () — flags are not callable in discord.py 2.x.
SEND_MESSAGES_FLAG = discord.Permissions.send_messages
SEND_MESSAGES_IN_THREADS_FLAG = discord.Permissions.send_messages_in_threads
CREATE_PUBLIC_THREADS_FLAG = discord.Permissions.create_public_threads

# Bitmasks for bitwise ops on PermissionOverwrite pair() values (flag uses .flag).
SEND_MESSAGES_BIT: int = SEND_MESSAGES_FLAG.flag
SEND_MESSAGES_IN_THREADS_BIT: int = SEND_MESSAGES_IN_THREADS_FLAG.flag
CREATE_PUBLIC_THREADS_BIT: int = CREATE_PUBLIC_THREADS_FLAG.flag

SNAPSHOT_KEY_SEND_MESSAGES = "send_messages"
SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS = "send_messages_in_threads"
SNAPSHOT_KEY_CREATE_PUBLIC_THREADS = "create_public_threads"
SNAPSHOT_KEY_APPLIED = "_applied"

BitPair = tuple[str, int]

# Map each scope to the (snapshot_key, bit) pairs it manages.
_SCOPE_BITS: dict[MuteScope, tuple[tuple[str, int], ...]] = {
    MuteScope.CHAT_ONLY: ((SNAPSHOT_KEY_SEND_MESSAGES, SEND_MESSAGES_BIT),),
    MuteScope.THREADS_ONLY: (
        (SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS, SEND_MESSAGES_IN_THREADS_BIT),
    ),
    MuteScope.CHAT_AND_THREADS: (
        (SNAPSHOT_KEY_SEND_MESSAGES, SEND_MESSAGES_BIT),
        (SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS, SEND_MESSAGES_IN_THREADS_BIT),
    ),
    MuteScope.FORUM: (
        (SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS, SEND_MESSAGES_IN_THREADS_BIT),
        (SNAPSHOT_KEY_CREATE_PUBLIC_THREADS, CREATE_PUBLIC_THREADS_BIT),
    ),
}


def scope_bit_pairs(scope: MuteScope) -> tuple[tuple[str, int], ...]:
    """Return the (snapshot_key, permission_bit) pairs managed by a scope."""
    return _SCOPE_BITS[scope]


def deny_flag_value_for_scope(scope: MuteScope) -> int:
    """Bitmask of all permission flags the bot denies for a given scope."""
    value = 0
    for _key, bit in _SCOPE_BITS[scope]:
        value |= bit
    return value


def capture_state_for_scope(
    overwrite: discord.PermissionOverwrite | None,
    scope: MuteScope,
) -> dict[str, Any]:
    """
    Capture the tri-state of every bit managed by ``scope`` before applying mute.

    Values per key: true (allow), false (deny), null (inherit / no explicit bit).
    """
    state: dict[str, Any] = {}
    if overwrite is None:
        for key, _bit in _SCOPE_BITS[scope]:
            state[key] = None
        return state

    allow, deny = overwrite.pair()
    for key, bit in _SCOPE_BITS[scope]:
        if allow.value & bit:
            state[key] = True
        elif deny.value & bit:
            state[key] = False
        else:
            state[key] = None
    return state


def snapshot_from_json(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate snapshot dict from database."""
    if data is None:
        return None
    return dict(data)


def has_scope_deny(
    overwrite: discord.PermissionOverwrite | None,
    scope: MuteScope,
) -> bool:
    """Return True if overwrite explicitly denies any bit managed by ``scope``."""
    if overwrite is None:
        return False
    _allow, deny = overwrite.pair()
    return bool(deny.value & deny_flag_value_for_scope(scope))


def has_full_scope_deny(
    overwrite: discord.PermissionOverwrite | None,
    scope: MuteScope,
) -> bool:
    """Return True if every permission bit in ``scope`` is explicitly denied."""
    if overwrite is None:
        return False
    _allow, deny = overwrite.pair()
    mask = deny_flag_value_for_scope(scope)
    return (deny.value & mask) == mask


def empty_scope_snapshot(scope: MuteScope) -> dict[str, Any]:
    """Inherit (null) snapshot for every bit managed by ``scope``."""
    return {key: None for key, _bit in _SCOPE_BITS[scope]}


def compute_reverted_pair(
    allow: discord.Permissions,
    deny: discord.Permissions,
    snapshot: dict[str, Any] | None,
    pairs: Sequence[tuple[str, int]],
) -> tuple[discord.Permissions, discord.Permissions]:
    """
    Remove only the given ``pairs`` deny bits and restore their prior state.

    Bits not in ``pairs`` are left untouched so that an independent mute on
    another scope (or an overlapping scope still active) keeps its deny.
    """
    new_allow_value = allow.value
    new_deny_value = deny.value

    for key, bit in pairs:
        # Clear both allow/deny for this bit, then restore from snapshot.
        new_allow_value &= ~bit
        new_deny_value &= ~bit
        prior = None if snapshot is None else snapshot.get(key)
        if prior is True:
            new_allow_value |= bit
        elif prior is False:
            new_deny_value |= bit

    return (
        discord.Permissions(new_allow_value),
        discord.Permissions(new_deny_value),
    )


def compute_reverted_pair_for_scope(
    allow: discord.Permissions,
    deny: discord.Permissions,
    snapshot: dict[str, Any] | None,
    scope: MuteScope,
) -> tuple[discord.Permissions, discord.Permissions]:
    """Revert all bits managed by ``scope`` (convenience wrapper)."""
    return compute_reverted_pair(allow, deny, snapshot, _SCOPE_BITS[scope])


def applied_keys_from_snapshot(snapshot: dict[str, Any] | None) -> list[str] | None:
    """Return the list of snapshot keys the bot applied, or None if not tracked."""
    if snapshot is None:
        return None
    applied = snapshot.get(SNAPSHOT_KEY_APPLIED)
    if applied is None:
        return None
    return list(applied)


def applied_bit_pairs(
    scope: MuteScope,
    snapshot: dict[str, Any] | None,
) -> list[BitPair]:
    """Return bit pairs to revert based on what was actually applied."""
    applied_keys = applied_keys_from_snapshot(snapshot)
    if applied_keys is None:
        return list(_SCOPE_BITS[scope])
    key_to_bit = {key: bit for key, bit in _SCOPE_BITS[scope]}
    return [(key, key_to_bit[key]) for key in applied_keys if key in key_to_bit]


def merge_applied_into_snapshot(
    snapshot: dict[str, Any],
    applied_pairs: Sequence[BitPair],
) -> dict[str, Any]:
    """Merge newly applied bit keys into snapshot ``_applied`` list."""
    merged = dict(snapshot)
    existing = set(applied_keys_from_snapshot(merged) or [])
    for key, _bit in applied_pairs:
        existing.add(key)
    merged[SNAPSHOT_KEY_APPLIED] = sorted(existing)
    return merged


def has_scope_deny_for_applied(
    overwrite: discord.PermissionOverwrite | None,
    scope: MuteScope,
    snapshot: dict[str, Any] | None,
) -> bool:
    """
    Return True if overwrite denies bits that indicate an active mute.

    Uses ``_applied`` keys when present; otherwise any scope bit deny counts.
    For FORUM, ``send_messages_in_threads`` deny alone is sufficient.
    """
    if overwrite is None:
        return False
    _allow, deny = overwrite.pair()
    pairs = applied_bit_pairs(scope, snapshot)
    if not pairs:
        return has_scope_deny(overwrite, scope)
    return any(deny.value & bit for _key, bit in pairs)


def has_full_scope_deny_for_applied(
    overwrite: discord.PermissionOverwrite | None,
    scope: MuteScope,
    snapshot: dict[str, Any] | None,
) -> bool:
    """Return True if every applied (or all scope) bit is explicitly denied."""
    if overwrite is None:
        return False
    _allow, deny = overwrite.pair()
    pairs = applied_bit_pairs(scope, snapshot)
    if not pairs:
        return has_full_scope_deny(overwrite, scope)
    return all(deny.value & bit for _key, bit in pairs)
