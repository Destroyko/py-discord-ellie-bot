"""Load application configuration from YAML and environment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
import os

from core.exceptions import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ROLES_PATH = PROJECT_ROOT / "config" / "roles.yaml"


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for a single-guild bot instance."""

    discord_token: str
    guild_id: int
    database_path: Path
    log_level: str
    prefix: str
    moderator_commands_channel_id: int
    bot_logs_channel_id: int
    moderator_role_ids: tuple[int, ...]
    mention_gif_enabled: bool
    mention_gif_cooldown_seconds: int
    mention_gifs_dir: Path


def _require_int(data: dict, key: str) -> int:
    if key not in data:
        raise ConfigError(f"Missing required config key: {key}")
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"Config key {key} must be an integer")
    return value


def load_config(
    config_path: Path | None = None,
    roles_path: Path | None = None,
    env_path: Path | None = None,
) -> AppConfig:
    """
    Load configuration from .env, config.yaml, and roles.yaml.

    :raises ConfigError: if required values are missing or invalid.
    """
    load_dotenv(env_path or PROJECT_ROOT / ".env")

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise ConfigError("DISCORD_TOKEN is not set in environment (.env)")

    cfg_file = config_path or DEFAULT_CONFIG_PATH
    if not cfg_file.is_file():
        raise ConfigError(
            f"Config file not found: {cfg_file}. "
            "Copy config/config.yaml.example to config/config.yaml"
        )

    with cfg_file.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    roles_file = roles_path or DEFAULT_ROLES_PATH
    if not roles_file.is_file():
        raise ConfigError(
            f"Roles file not found: {roles_file}. "
            "Copy config/roles.yaml.example to config/roles.yaml"
        )

    with roles_file.open(encoding="utf-8") as fh:
        roles_raw = yaml.safe_load(fh) or {}

    role_ids_raw = roles_raw.get("role_ids", [])
    if not isinstance(role_ids_raw, list):
        raise ConfigError("roles.yaml: role_ids must be a list")

    role_ids: list[int] = []
    seen: set[int] = set()
    for rid in role_ids_raw:
        if not isinstance(rid, int) or isinstance(rid, bool):
            raise ConfigError("roles.yaml: each role_id must be an integer")
        if rid in seen:
            raise ConfigError(f"roles.yaml: duplicate role_id {rid}")
        seen.add(rid)
        role_ids.append(rid)

    if not role_ids:
        raise ConfigError("roles.yaml: role_ids must contain at least one role")

    db_path = Path(raw.get("database_path", "data/bot.db"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    log_level = str(raw.get("log_level", "INFO")).upper()

    mention_gif_enabled = raw.get("mention_gif_enabled", True)
    if not isinstance(mention_gif_enabled, bool):
        raise ConfigError("config.yaml: mention_gif_enabled must be a boolean")

    mention_gif_cooldown_seconds = raw.get("mention_gif_cooldown_seconds", 600)
    if (
        not isinstance(mention_gif_cooldown_seconds, int)
        or isinstance(mention_gif_cooldown_seconds, bool)
        or mention_gif_cooldown_seconds < 1
    ):
        raise ConfigError(
            "config.yaml: mention_gif_cooldown_seconds must be a positive integer"
        )

    mention_gifs_path = Path(raw.get("mention_gifs_dir", "assets/mention_gifs"))
    if not mention_gifs_path.is_absolute():
        mention_gifs_path = PROJECT_ROOT / mention_gifs_path

    return AppConfig(
        discord_token=token,
        guild_id=_require_int(raw, "guild_id"),
        database_path=db_path,
        log_level=log_level,
        prefix=str(raw.get("prefix", "!")),
        moderator_commands_channel_id=_require_int(raw, "moderator_commands_channel_id"),
        bot_logs_channel_id=_require_int(raw, "bot_logs_channel_id"),
        moderator_role_ids=tuple(role_ids),
        mention_gif_enabled=mention_gif_enabled,
        mention_gif_cooldown_seconds=mention_gif_cooldown_seconds,
        mention_gifs_dir=mention_gifs_path,
    )
