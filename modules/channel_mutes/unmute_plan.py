"""Plan bulk unmute: collect records, group by channel, notification scope."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from database.models import ChannelMute
from modules.channel_mutes.mute_scope import MuteScope
from modules.channel_mutes.repository import ChannelMuteRepository


@dataclass(frozen=True)
class UnmuteBatchResult:
    """Outcome of removing one or more mute records in a single operation."""

    succeeded: list[ChannelMute] = field(default_factory=list)
    failed: list[tuple[ChannelMute, str]] = field(default_factory=list)

    @property
    def record_count(self) -> int:
        return len(self.succeeded)

    @property
    def channel_count(self) -> int:
        return len(unique_channel_ids(self.succeeded))


def collect_unmute_records(
    repository: ChannelMuteRepository,
    guild_id: int,
    user_id: int,
    *,
    channel_id: int | None,
    scope_filter: MuteScope | None,
) -> list[ChannelMute]:
    """Active mutes for a user, optionally filtered by channel and/or scope."""
    records = repository.list_active_for_user(guild_id, user_id)
    if channel_id is not None:
        records = [record for record in records if record.channel_id == channel_id]
    if scope_filter is not None:
        records = [record for record in records if record.scope == scope_filter]
    return records


def unique_channel_ids(records: list[ChannelMute]) -> set[int]:
    """Distinct parent text channel ids among mute records."""
    return {record.channel_id for record in records}


def group_records_by_channel(
    records: list[ChannelMute],
) -> dict[int, list[ChannelMute]]:
    """Group mute records by ``channel_id``."""
    grouped: dict[int, list[ChannelMute]] = defaultdict(list)
    for record in records:
        grouped[record.channel_id].append(record)
    return dict(grouped)


def notification_scope_for_channel(removed_scopes: set[MuteScope]) -> MuteScope:
    """
    Pick DM/mod-notice scope text for what was removed on one channel.

    Combined «чат и ветки» only when both aspects were cleared in this operation.
    Forum mutes keep ``FORUM`` phrasing (not «ветки чата»).
    """
    if MuteScope.FORUM in removed_scopes:
        return MuteScope.FORUM
    chat_removed = any(scope.affects_chat for scope in removed_scopes)
    threads_removed = any(scope.affects_threads for scope in removed_scopes)
    if chat_removed and threads_removed:
        return MuteScope.CHAT_AND_THREADS
    if threads_removed:
        return MuteScope.THREADS_ONLY
    return MuteScope.CHAT_ONLY
