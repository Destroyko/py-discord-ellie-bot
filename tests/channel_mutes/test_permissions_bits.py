"""Tests for permission snapshot and revert logic."""

from __future__ import annotations

from typing import Any

import discord
import pytest

from modules.channel_mutes.permissions_bits import (
    SEND_MESSAGES_BIT,
    SNAPSHOT_KEY_SEND_MESSAGES,
    capture_send_messages_state,
    combined_deny_flag_value,
    compute_reverted_send_messages_pair,
    has_our_send_messages_deny,
)


def _pair(allow_bits: int = 0, deny_bits: int = 0) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite.from_pair(
        discord.Permissions(allow_bits),
        discord.Permissions(deny_bits),
    )


class TestCaptureSendMessagesState:
    def test_none_overwrite(self) -> None:
        assert capture_send_messages_state(None) == {SNAPSHOT_KEY_SEND_MESSAGES: None}

    def test_allow(self) -> None:
        ow = _pair(allow_bits=SEND_MESSAGES_BIT)
        assert capture_send_messages_state(ow) == {SNAPSHOT_KEY_SEND_MESSAGES: True}

    def test_deny(self) -> None:
        ow = _pair(deny_bits=SEND_MESSAGES_BIT)
        assert capture_send_messages_state(ow) == {SNAPSHOT_KEY_SEND_MESSAGES: False}

    def test_inherit(self) -> None:
        ow = _pair()
        assert capture_send_messages_state(ow) == {SNAPSHOT_KEY_SEND_MESSAGES: None}


class TestHasOurSendMessagesDeny:
    def test_no_overwrite(self) -> None:
        assert has_our_send_messages_deny(None) is False

    def test_with_deny(self) -> None:
        assert has_our_send_messages_deny(_pair(deny_bits=SEND_MESSAGES_BIT)) is True

    def test_without_deny(self) -> None:
        assert has_our_send_messages_deny(_pair()) is False


class TestCombinedDenyFlagValue:
    def test_matches_send_messages_bit(self) -> None:
        assert combined_deny_flag_value() == SEND_MESSAGES_BIT


class TestComputeRevertedSendMessagesPair:
    @pytest.mark.parametrize(
        ("allow_bits", "deny_bits", "snapshot", "expected_allow", "expected_deny"),
        [
            # Bot deny removed; restore prior allow
            (0, SEND_MESSAGES_BIT, {SNAPSHOT_KEY_SEND_MESSAGES: True}, SEND_MESSAGES_BIT, 0),
            # Bot deny removed; restore prior deny
            (0, SEND_MESSAGES_BIT, {SNAPSHOT_KEY_SEND_MESSAGES: False}, 0, SEND_MESSAGES_BIT),
            # Bot deny removed; restore inherit
            (0, SEND_MESSAGES_BIT, {SNAPSHOT_KEY_SEND_MESSAGES: None}, 0, 0),
            (SEND_MESSAGES_BIT, SEND_MESSAGES_BIT, {SNAPSHOT_KEY_SEND_MESSAGES: True}, SEND_MESSAGES_BIT, 0),
            # No snapshot
            (0, SEND_MESSAGES_BIT, None, 0, 0),
            # No bot deny in input — still strips bit
            (0, 0, {SNAPSHOT_KEY_SEND_MESSAGES: None}, 0, 0),
        ],
    )
    def test_revert_matrix(
        self,
        allow_bits: int,
        deny_bits: int,
        snapshot: dict[str, Any] | None,
        expected_allow: int,
        expected_deny: int,
    ) -> None:
        allow, deny = compute_reverted_send_messages_pair(
            discord.Permissions(allow_bits),
            discord.Permissions(deny_bits),
            snapshot,
        )
        assert allow.value == expected_allow
        assert deny.value == expected_deny

    def test_empty_after_revert_from_inherit(self) -> None:
        """OverwriteManager deletes overwrite when pair is (0, 0)."""
        allow, deny = compute_reverted_send_messages_pair(
            discord.Permissions.none(),
            discord.Permissions(SEND_MESSAGES_BIT),
            {SNAPSHOT_KEY_SEND_MESSAGES: None},
        )
        assert allow.value == 0 and deny.value == 0
