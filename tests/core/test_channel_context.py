"""Tests for channel classification and mute target resolution."""

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
    resolve_mute_target,
)
from core.config_loader import AppConfig
from core.exceptions import ValidationError
from modules.channel_mutes.mute_scope import MuteScope
from tests.conftest import app_config, make_text_channel, make_thread


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


class TestResolveMuteTarget:
    def test_text_channel_defaults_to_chat(self, config: AppConfig) -> None:
        channel = make_text_channel(channel_id=500)
        inv = InvocationContext(kind=ChannelKind.PUBLIC, channel=channel)
        target = resolve_mute_target(inv, None, None, config)
        assert target.overwrite_channel is channel
        assert target.scope is MuteScope.CHAT_ONLY
        assert target.target_is_thread is False
        assert target.channel_param_required is False

    def test_thread_defaults_to_threads_and_uses_parent(self, config: AppConfig) -> None:
        parent = make_text_channel(channel_id=500)
        thread = make_thread(thread_id=900, parent=parent)
        inv = InvocationContext(kind=ChannelKind.PUBLIC, channel=thread)
        target = resolve_mute_target(inv, None, None, config)
        assert target.overwrite_channel is parent
        assert target.scope is MuteScope.THREADS_ONLY
        assert target.target_is_thread is True

    def test_text_channel_scope_all(self, config: AppConfig) -> None:
        channel = make_text_channel(channel_id=500)
        inv = InvocationContext(kind=ChannelKind.PUBLIC, channel=channel)
        target = resolve_mute_target(inv, None, "all", config)
        assert target.scope is MuteScope.CHAT_AND_THREADS

    def test_text_channel_scope_threads(self, config: AppConfig) -> None:
        channel = make_text_channel(channel_id=500)
        inv = InvocationContext(kind=ChannelKind.PUBLIC, channel=channel)
        target = resolve_mute_target(inv, None, "threads", config)
        assert target.scope is MuteScope.THREADS_ONLY

    def test_thread_scope_chat_rejected(self, config: AppConfig) -> None:
        thread = make_thread(thread_id=900)
        inv = InvocationContext(kind=ChannelKind.PUBLIC, channel=thread)
        with pytest.raises(ValidationError, match="ветки"):
            resolve_mute_target(inv, None, "chat", config)

    def test_mod_commands_requires_channel(self, config: AppConfig) -> None:
        mod_ch = make_text_channel(channel_id=config.moderator_commands_channel_id)
        inv = InvocationContext(kind=ChannelKind.MOD_COMMANDS, channel=mod_ch)
        with pytest.raises(ValidationError, match="channel"):
            resolve_mute_target(inv, None, None, config)

    def test_mod_commands_thread_param_defaults_threads(self, config: AppConfig) -> None:
        mod_ch = make_text_channel(channel_id=config.moderator_commands_channel_id)
        parent = make_text_channel(channel_id=500)
        thread = make_thread(thread_id=900, parent=parent)
        inv = InvocationContext(kind=ChannelKind.MOD_COMMANDS, channel=mod_ch)
        target = resolve_mute_target(inv, thread, None, config)
        assert target.overwrite_channel is parent
        assert target.scope is MuteScope.THREADS_ONLY
        assert target.channel_param_required is True

    def test_forbidden_target_log_channel(self, config: AppConfig) -> None:
        mod_ch = make_text_channel(channel_id=config.moderator_commands_channel_id)
        log_ch = make_text_channel(channel_id=config.bot_logs_channel_id)
        inv = InvocationContext(kind=ChannelKind.MOD_COMMANDS, channel=mod_ch)
        with pytest.raises(ValidationError, match="наказание"):
            resolve_mute_target(inv, log_ch, None, config)

    def test_forum_thread_rejected(self, config: AppConfig) -> None:
        forum_parent = MagicMock(spec=discord.ForumChannel)
        forum_parent.id = 600
        thread = MagicMock(spec=discord.Thread)
        thread.parent = forum_parent
        thread.parent_id = 600
        inv = InvocationContext(kind=ChannelKind.PUBLIC, channel=thread)
        with pytest.raises(ValidationError, match="форум"):
            resolve_mute_target(inv, None, None, config)


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

    def test_thread_ok_public(self, config: AppConfig) -> None:
        thread = make_thread(thread_id=900)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.channel = thread
        ctx = resolve_invocation_channel(interaction, config)
        assert ctx.channel is thread
        assert ctx.kind == ChannelKind.PUBLIC

    def test_thread_inherits_mod_commands_from_parent(self, config: AppConfig) -> None:
        parent = make_text_channel(channel_id=config.moderator_commands_channel_id)
        thread = make_thread(thread_id=900, parent=parent)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.channel = thread
        ctx = resolve_invocation_channel(interaction, config)
        assert ctx.kind == ChannelKind.MOD_COMMANDS
