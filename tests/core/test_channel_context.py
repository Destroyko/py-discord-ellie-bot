"""Tests for channel classification and target resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

import discord
import pytest

from core.channel_context import (
    ChannelKind,
    InvocationContext,
    assert_commands_allowed_in_channel,
    classify_channel,
    is_ephemeral_mute_command_reply,
    is_ephemeral_reply,
    resolve_invocation_channel,
    resolve_target_channel,
)
from core.config_loader import AppConfig
from core.exceptions import ValidationError
from tests.conftest import app_config, make_text_channel


@pytest.fixture
def config(app_config: AppConfig) -> AppConfig:
    return app_config


class TestClassifyChannel:
    def test_public(self, config: AppConfig) -> None:
        assert classify_channel(999, config) == ChannelKind.PUBLIC

    def test_mod_commands(self, config: AppConfig) -> None:
        assert classify_channel(config.moderator_commands_channel_id, config) == ChannelKind.MOD_COMMANDS

    def test_bot_logs(self, config: AppConfig) -> None:
        assert classify_channel(config.bot_logs_channel_id, config) == ChannelKind.BOT_LOGS


class TestAssertCommandsAllowedInChannel:
    def test_bot_logs_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="логов"):
            assert_commands_allowed_in_channel(ChannelKind.BOT_LOGS)

    def test_help_only_in_mod_commands(self) -> None:
        with pytest.raises(ValidationError, match="бот-команд"):
            assert_commands_allowed_in_channel(ChannelKind.PUBLIC, for_help=True)

    def test_help_ok_in_mod_commands(self) -> None:
        assert_commands_allowed_in_channel(ChannelKind.MOD_COMMANDS, for_help=True)


class TestEphemeralFlags:
    def test_ephemeral_reply_public_only(self) -> None:
        assert is_ephemeral_reply(ChannelKind.PUBLIC) is True
        assert is_ephemeral_reply(ChannelKind.MOD_COMMANDS) is False

    def test_mute_command_ephemeral(self) -> None:
        assert is_ephemeral_mute_command_reply(ChannelKind.PUBLIC) is True
        assert is_ephemeral_mute_command_reply(ChannelKind.MOD_COMMANDS) is True
        assert is_ephemeral_mute_command_reply(ChannelKind.BOT_LOGS) is False


class TestResolveTargetChannel:
    def test_public_defaults_to_invocation(self, config: AppConfig) -> None:
        channel = make_text_channel(channel_id=500)
        inv = InvocationContext(kind=ChannelKind.PUBLIC, channel=channel)
        ctx = resolve_target_channel(inv, None, config)
        assert ctx.channel is channel
        assert ctx.channel_param_required is False

    def test_mod_commands_requires_channel(self, config: AppConfig) -> None:
        mod_ch = make_text_channel(channel_id=config.moderator_commands_channel_id)
        inv = InvocationContext(kind=ChannelKind.MOD_COMMANDS, channel=mod_ch)
        with pytest.raises(ValidationError, match="channel"):
            resolve_target_channel(inv, None, config)

    def test_forbidden_target_log_channel(self, config: AppConfig) -> None:
        mod_ch = make_text_channel(channel_id=config.moderator_commands_channel_id)
        log_ch = make_text_channel(channel_id=config.bot_logs_channel_id)
        inv = InvocationContext(kind=ChannelKind.MOD_COMMANDS, channel=mod_ch)
        with pytest.raises(ValidationError, match="наказание"):
            resolve_target_channel(inv, log_ch, config)


class TestResolveInvocationChannel:
    def test_non_text_channel_raises(self, config: AppConfig) -> None:
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.channel = MagicMock(spec=discord.VoiceChannel)
        with pytest.raises(ValidationError, match="текстовых"):
            resolve_invocation_channel(interaction, config)

    def test_text_channel_ok(self, config: AppConfig) -> None:
        channel = make_text_channel(channel_id=500)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.channel = channel
        ctx = resolve_invocation_channel(interaction, config)
        assert ctx.channel is channel
        assert ctx.kind == ChannelKind.PUBLIC
