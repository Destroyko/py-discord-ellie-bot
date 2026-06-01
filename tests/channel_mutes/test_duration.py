"""Tests for duration parsing and formatting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.exceptions import ValidationError
from modules.channel_mutes.duration import (
    compute_expire_at,
    format_duration,
    parse_duration,
)


class TestParseDuration:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("10m", timedelta(minutes=10)),
            ("2h", timedelta(hours=2)),
            ("3d", timedelta(days=3)),
            ("1m", timedelta(minutes=1)),
            ("28d", timedelta(days=28)),
            (" 5M ", timedelta(minutes=5)),
        ],
    )
    def test_valid(self, value: str, expected: timedelta) -> None:
        assert parse_duration(value) == expected

    @pytest.mark.parametrize(
        "value",
        ["", "0m", "10x", "29d", "1s", "abc", "10", "m10"],
    )
    def test_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError):
            parse_duration(value)


class TestComputeExpireAt:
    def test_aware_utc(self) -> None:
        now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        result = compute_expire_at(timedelta(hours=1), now=now)
        assert result == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)

    def test_naive_treated_as_utc(self) -> None:
        now = datetime(2026, 6, 1, 12, 0)
        result = compute_expire_at(timedelta(minutes=30), now=now)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12 and result.minute == 30


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (timedelta(minutes=90), "90m"),
            (timedelta(hours=2), "2h"),
            (timedelta(days=2), "2d"),
            (timedelta(minutes=45), "45m"),
            (timedelta(seconds=30), "1m"),
        ],
    )
    def test_format(self, delta: timedelta, expected: str) -> None:
        assert format_duration(delta) == expected
