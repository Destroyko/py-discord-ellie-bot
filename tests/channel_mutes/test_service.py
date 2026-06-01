"""Tests for ChannelMuteService critical paths."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from core.config_loader import AppConfig
from database.models import ChannelMute
from modules.channel_mutes.repository import ChannelMuteRepository
from modules.channel_mutes.service import ChannelMuteService, UnmuteSource
from modules.channel_mutes.unmute_outcome import UnmuteOutcome
from modules.channel_mutes.user_presence import UserPresence
from tests.conftest import (
    make_member,
    make_text_channel,
    overwrite_with_deny,
    overwrite_without_deny,
    sample_mute,
)


@pytest.fixture
def config(app_config: AppConfig) -> AppConfig:
    return app_config


@pytest.fixture
def bot() -> MagicMock:
    return MagicMock(spec=discord.Client)


@pytest.fixture
def overwrite_mgr() -> MagicMock:
    mgr = MagicMock()
    mgr.capture_snapshot = AsyncMock(return_value={"send_messages": None})
    mgr.apply_mute = AsyncMock()
    mgr.revert_mute = AsyncMock()
    mgr.rollback_after_failed_db = AsyncMock()
    mgr.revert_mute_by_user_id = AsyncMock()
    return mgr


@pytest.fixture
def dm() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mod_notifier() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def audit() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(
    bot: MagicMock,
    config: AppConfig,
    mute_repo: ChannelMuteRepository,
    overwrite_mgr: MagicMock,
    dm: AsyncMock,
    mod_notifier: AsyncMock,
    audit: AsyncMock,
) -> ChannelMuteService:
    svc = ChannelMuteService(
        bot,
        config,
        mute_repo,
        overwrite_manager=overwrite_mgr,
        dm_notifier=dm,
        moderator_notifier=mod_notifier,
        audit_log=audit,
    )
    svc.set_scheduler_hooks(
        on_scheduled=AsyncMock(),
        on_cancelled=AsyncMock(),
    )
    return svc


def _guild_and_channel() -> tuple[MagicMock, MagicMock]:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 100
    guild.name = "Test Guild"
    channel = make_text_channel(channel_id=400, guild_id=100)
    channel.guild = guild
    return guild, channel


class TestMuteChannelNew:
    async def test_order_snapshot_apply_insert_schedule(
        self,
        service: ChannelMuteService,
        overwrite_mgr: MagicMock,
        mute_repo: ChannelMuteRepository,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        mod = make_member(member_id=60, role_ids=(10,))
        calls: list[str] = []

        async def track_snapshot(*_a: object, **_k: object) -> dict:
            calls.append("snapshot")
            return {"send_messages": None}

        async def track_apply(*_a: object, **_k: object) -> None:
            calls.append("apply")

        overwrite_mgr.capture_snapshot = track_snapshot
        overwrite_mgr.apply_mute = track_apply

        scheduled = service._on_scheduled
        assert scheduled is not None

        async def track_schedule(mute_id: int, _exp: datetime) -> None:
            calls.append(f"schedule:{mute_id}")

        service._on_scheduled = track_schedule

        saved, extended = await service.mute_channel(
            guild=guild,
            channel=channel,
            target=target,
            moderator=mod,
            duration_delta=timedelta(hours=1),
            duration_text="1h",
            reason="spam",
        )

        assert extended is False
        assert saved.id is not None
        assert calls == ["snapshot", "apply", f"schedule:{saved.id}"]

    async def test_rollback_on_db_failure(
        self,
        service: ChannelMuteService,
        overwrite_mgr: MagicMock,
        mute_repo: ChannelMuteRepository,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        mod = make_member(member_id=60, role_ids=(10,))
        snapshot = {"send_messages": True}

        overwrite_mgr.capture_snapshot = AsyncMock(return_value=snapshot)

        original_insert = mute_repo.insert

        def failing_insert(_mute: ChannelMute) -> ChannelMute:
            raise RuntimeError("db down")

        mute_repo.insert = failing_insert  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="db down"):
            await service.mute_channel(
                guild=guild,
                channel=channel,
                target=target,
                moderator=mod,
                duration_delta=timedelta(hours=1),
                duration_text="1h",
                reason=None,
            )

        overwrite_mgr.rollback_after_failed_db.assert_awaited_once_with(
            channel, target, snapshot
        )
        mute_repo.insert = original_insert  # type: ignore[method-assign]


class TestMuteChannelExtend:
    async def test_extend_skips_discord_overwrite(
        self,
        service: ChannelMuteService,
        overwrite_mgr: MagicMock,
        mute_repo: ChannelMuteRepository,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        mod = make_member(member_id=60, role_ids=(10,))
        existing = mute_repo.insert(
            sample_mute(mute_id=None, snapshot={"send_messages": False})
        )

        saved, extended = await service.mute_channel(
            guild=guild,
            channel=channel,
            target=target,
            moderator=mod,
            duration_delta=timedelta(hours=3),
            duration_text="3h",
            reason="more",
        )

        assert extended is True
        assert saved.id == existing.id
        overwrite_mgr.capture_snapshot.assert_not_awaited()
        overwrite_mgr.apply_mute.assert_not_awaited()
        service._on_cancelled.assert_awaited_once_with(existing.id)  # type: ignore[attr-defined]
        service._on_scheduled.assert_awaited()  # type: ignore[attr-defined]


class TestUnmuteChannel:
    async def test_no_db_record_returns_false(
        self,
        service: ChannelMuteService,
        overwrite_mgr: MagicMock,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        channel.overwrites_for = MagicMock(return_value=overwrite_without_deny())
        result = await service.unmute_channel(
            guild=guild,
            channel=channel,
            target=target,
            moderator=make_member(member_id=60),
            source=UnmuteSource.MANUAL,
        )
        assert result is False
        overwrite_mgr.revert_mute.assert_not_awaited()

    async def test_db_without_deny_manual_true(
        self,
        service: ChannelMuteService,
        mute_repo: ChannelMuteRepository,
        overwrite_mgr: MagicMock,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        saved = mute_repo.insert(sample_mute(mute_id=None))
        channel.overwrites_for = MagicMock(return_value=overwrite_without_deny())

        result = await service.unmute_channel(
            guild=guild,
            channel=channel,
            target=target,
            moderator=make_member(member_id=60),
            source=UnmuteSource.MANUAL,
        )

        assert result is True
        assert mute_repo.get_by_id(saved.id) is None
        overwrite_mgr.revert_mute.assert_not_awaited()
        service._on_cancelled.assert_awaited_once_with(saved.id)  # type: ignore[attr-defined]

    async def test_db_without_deny_auto_false(
        self,
        service: ChannelMuteService,
        mute_repo: ChannelMuteRepository,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        saved = mute_repo.insert(sample_mute(mute_id=None))
        channel.overwrites_for = MagicMock(return_value=overwrite_without_deny())

        result = await service.unmute_channel(
            guild=guild,
            channel=channel,
            target=target,
            moderator=None,
            source=UnmuteSource.AUTO,
        )

        assert result is False
        assert mute_repo.get_by_id(saved.id) is None

    async def test_full_unmute_with_deny(
        self,
        service: ChannelMuteService,
        mute_repo: ChannelMuteRepository,
        overwrite_mgr: MagicMock,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        saved = mute_repo.insert(
            sample_mute(mute_id=None, snapshot={"send_messages": None})
        )
        channel.overwrites_for = MagicMock(return_value=overwrite_with_deny())

        result = await service.unmute_channel(
            guild=guild,
            channel=channel,
            target=target,
            moderator=make_member(member_id=60),
            source=UnmuteSource.MANUAL,
        )

        assert result is True
        assert mute_repo.get_by_id(saved.id) is None
        overwrite_mgr.revert_mute.assert_awaited_once()

    async def test_reapply_mute_on_db_delete_failure(
        self,
        service: ChannelMuteService,
        mute_repo: ChannelMuteRepository,
        overwrite_mgr: MagicMock,
    ) -> None:
        guild, channel = _guild_and_channel()
        target = make_member(member_id=50)
        saved = mute_repo.insert(sample_mute(mute_id=None))
        channel.overwrites_for = MagicMock(return_value=overwrite_with_deny())

        original_delete = mute_repo.delete

        def failing_delete(_mute_id: int) -> None:
            raise RuntimeError("delete failed")

        mute_repo.delete = failing_delete  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="delete failed"):
            await service.unmute_channel(
                guild=guild,
                channel=channel,
                target=target,
                moderator=make_member(member_id=60),
                source=UnmuteSource.MANUAL,
            )

        overwrite_mgr.apply_mute.assert_awaited_once_with(channel, target)
        mute_repo.delete = original_delete  # type: ignore[method-assign]


class TestUnmuteById:
    async def test_record_gone(self, service: ChannelMuteService) -> None:
        assert await service.unmute_by_id(99999) == UnmuteOutcome.RECORD_GONE

    async def test_not_yet_expired_left_guild(
        self,
        service: ChannelMuteService,
        mute_repo: ChannelMuteRepository,
        bot: MagicMock,
    ) -> None:
        saved = mute_repo.insert(
            sample_mute(mute_id=None, expire_in=timedelta(hours=5))
        )
        assert saved.id is not None
        guild = MagicMock(spec=discord.Guild)
        guild.id = 100
        channel = make_text_channel()
        bot.get_guild = MagicMock(return_value=guild)
        guild.get_channel = MagicMock(return_value=channel)

        with patch(
            "modules.channel_mutes.service.resolve_user_presence",
            new_callable=AsyncMock,
            return_value=(UserPresence.LEFT_GUILD, None),
        ):
            outcome = await service.unmute_by_id(saved.id)

        assert outcome == UnmuteOutcome.NOT_YET_EXPIRED

    async def test_deleted_user_cleanup(
        self,
        service: ChannelMuteService,
        mute_repo: ChannelMuteRepository,
        bot: MagicMock,
        overwrite_mgr: MagicMock,
    ) -> None:
        saved = mute_repo.insert(sample_mute(mute_id=None))
        assert saved.id is not None
        guild = MagicMock(spec=discord.Guild)
        guild.id = 100
        channel = make_text_channel()
        channel.overwrites_for = MagicMock(return_value=overwrite_with_deny())
        bot.get_guild = MagicMock(return_value=guild)
        guild.get_channel = MagicMock(return_value=channel)

        with patch(
            "modules.channel_mutes.service.resolve_user_presence",
            new_callable=AsyncMock,
            return_value=(UserPresence.DELETED, None),
        ):
            outcome = await service.unmute_by_id(saved.id)

        assert outcome == UnmuteOutcome.DELETED_USER
        assert mute_repo.get_by_id(saved.id) is None
        overwrite_mgr.revert_mute_by_user_id.assert_awaited()
