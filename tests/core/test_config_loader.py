"""Tests for config loading helpers."""

from __future__ import annotations

import pytest

from core.config_loader import _require_int
from core.exceptions import ConfigError


class TestRequireInt:
    def test_missing_key(self) -> None:
        with pytest.raises(ConfigError, match="Missing"):
            _require_int({}, "guild_id")

    def test_not_int(self) -> None:
        with pytest.raises(ConfigError, match="integer"):
            _require_int({"guild_id": "123"}, "guild_id")

    def test_bool_rejected(self) -> None:
        with pytest.raises(ConfigError, match="integer"):
            _require_int({"guild_id": True}, "guild_id")

    def test_valid(self) -> None:
        assert _require_int({"guild_id": 42}, "guild_id") == 42
