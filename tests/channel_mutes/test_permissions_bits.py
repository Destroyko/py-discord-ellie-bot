"""Tests for permission snapshot and revert logic (scope-aware)."""

from __future__ import annotations

from typing import Any

import discord
import pytest

from modules.channel_mutes.mute_scope import MuteScope
from modules.channel_mutes.permissions_bits import (
    CREATE_PUBLIC_THREADS_BIT,
    SEND_MESSAGES_BIT,
    SEND_MESSAGES_IN_THREADS_BIT,
    SNAPSHOT_KEY_APPLIED,
    SNAPSHOT_KEY_CREATE_PUBLIC_THREADS,
    SNAPSHOT_KEY_SEND_MESSAGES,
    SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS,
    applied_bit_pairs,
    capture_state_for_scope,
    compute_reverted_pair,
    compute_reverted_pair_for_scope,
    deny_flag_value_for_scope,
    has_scope_deny,
    scope_bit_pairs,
)


def _pair(allow_bits: int = 0, deny_bits: int = 0) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite.from_pair(
        discord.Permissions(allow_bits),
        discord.Permissions(deny_bits),
    )


class TestDenyFlagValueForScope:
    def test_chat_only(self) -> None:
        assert deny_flag_value_for_scope(MuteScope.CHAT_ONLY) == SEND_MESSAGES_BIT

    def test_threads_only(self) -> None:
        assert (
            deny_flag_value_for_scope(MuteScope.THREADS_ONLY)
            == SEND_MESSAGES_IN_THREADS_BIT
        )

    def test_chat_and_threads(self) -> None:
        assert deny_flag_value_for_scope(MuteScope.CHAT_AND_THREADS) == (
            SEND_MESSAGES_BIT | SEND_MESSAGES_IN_THREADS_BIT
        )

    def test_forum(self) -> None:
        from modules.channel_mutes.permissions_bits import CREATE_PUBLIC_THREADS_BIT

        assert deny_flag_value_for_scope(MuteScope.FORUM) == (
            SEND_MESSAGES_IN_THREADS_BIT | CREATE_PUBLIC_THREADS_BIT
        )


class TestCaptureStateForScope:
    def test_none_overwrite_chat(self) -> None:
        assert capture_state_for_scope(None, MuteScope.CHAT_ONLY) == {
            SNAPSHOT_KEY_SEND_MESSAGES: None
        }

    def test_none_overwrite_both(self) -> None:
        assert capture_state_for_scope(None, MuteScope.CHAT_AND_THREADS) == {
            SNAPSHOT_KEY_SEND_MESSAGES: None,
            SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS: None,
        }

    def test_allow_chat(self) -> None:
        ow = _pair(allow_bits=SEND_MESSAGES_BIT)
        assert capture_state_for_scope(ow, MuteScope.CHAT_ONLY) == {
            SNAPSHOT_KEY_SEND_MESSAGES: True
        }

    def test_deny_threads(self) -> None:
        ow = _pair(deny_bits=SEND_MESSAGES_IN_THREADS_BIT)
        assert capture_state_for_scope(ow, MuteScope.THREADS_ONLY) == {
            SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS: False
        }

    def test_scope_only_captures_its_bits(self) -> None:
        ow = _pair(deny_bits=SEND_MESSAGES_IN_THREADS_BIT)
        # Capturing chat scope ignores the thread bit entirely.
        assert capture_state_for_scope(ow, MuteScope.CHAT_ONLY) == {
            SNAPSHOT_KEY_SEND_MESSAGES: None
        }


class TestHasScopeDeny:
    def test_no_overwrite(self) -> None:
        assert has_scope_deny(None, MuteScope.CHAT_ONLY) is False

    def test_chat_deny_detected(self) -> None:
        assert has_scope_deny(_pair(deny_bits=SEND_MESSAGES_BIT), MuteScope.CHAT_ONLY)

    def test_thread_deny_not_seen_by_chat_scope(self) -> None:
        ow = _pair(deny_bits=SEND_MESSAGES_IN_THREADS_BIT)
        assert has_scope_deny(ow, MuteScope.CHAT_ONLY) is False
        assert has_scope_deny(ow, MuteScope.THREADS_ONLY) is True


class TestComputeRevertedPairForScope:
    @pytest.mark.parametrize(
        ("allow_bits", "deny_bits", "snapshot", "expected_allow", "expected_deny"),
        [
            (0, SEND_MESSAGES_BIT, {SNAPSHOT_KEY_SEND_MESSAGES: True}, SEND_MESSAGES_BIT, 0),
            (0, SEND_MESSAGES_BIT, {SNAPSHOT_KEY_SEND_MESSAGES: False}, 0, SEND_MESSAGES_BIT),
            (0, SEND_MESSAGES_BIT, {SNAPSHOT_KEY_SEND_MESSAGES: None}, 0, 0),
            (0, SEND_MESSAGES_BIT, None, 0, 0),
        ],
    )
    def test_chat_revert_matrix(
        self,
        allow_bits: int,
        deny_bits: int,
        snapshot: dict[str, Any] | None,
        expected_allow: int,
        expected_deny: int,
    ) -> None:
        allow, deny = compute_reverted_pair_for_scope(
            discord.Permissions(allow_bits),
            discord.Permissions(deny_bits),
            snapshot,
            MuteScope.CHAT_ONLY,
        )
        assert allow.value == expected_allow
        assert deny.value == expected_deny


class TestComputeRevertedPairIndependence:
    def test_revert_chat_keeps_thread_deny(self) -> None:
        """Reverting only the chat pair leaves the thread deny untouched."""
        allow = discord.Permissions(0)
        deny = discord.Permissions(SEND_MESSAGES_BIT | SEND_MESSAGES_IN_THREADS_BIT)
        pairs = scope_bit_pairs(MuteScope.CHAT_ONLY)
        new_allow, new_deny = compute_reverted_pair(
            allow, deny, {SNAPSHOT_KEY_SEND_MESSAGES: None}, list(pairs)
        )
        assert new_allow.value == 0
        assert new_deny.value == SEND_MESSAGES_IN_THREADS_BIT

    def test_empty_pairs_changes_nothing(self) -> None:
        allow = discord.Permissions(0)
        deny = discord.Permissions(SEND_MESSAGES_BIT)
        new_allow, new_deny = compute_reverted_pair(allow, deny, None, [])
        assert new_allow.value == 0
        assert new_deny.value == SEND_MESSAGES_BIT


class TestAppliedBitPairs:
    def test_uses_applied_keys_when_present(self) -> None:
        snapshot = {
            SNAPSHOT_KEY_APPLIED: [SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS],
            SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS: None,
        }
        pairs = applied_bit_pairs(MuteScope.FORUM, snapshot)
        assert pairs == [
            (SNAPSHOT_KEY_SEND_MESSAGES_IN_THREADS, SEND_MESSAGES_IN_THREADS_BIT)
        ]

    def test_fallback_to_all_scope_bits(self) -> None:
        pairs = applied_bit_pairs(MuteScope.FORUM, None)
        assert len(pairs) == 2
        assert (SNAPSHOT_KEY_CREATE_PUBLIC_THREADS, CREATE_PUBLIC_THREADS_BIT) in pairs
