"""SQLite schema definitions."""

SCHEMA_VERSION = 2

CREATE_CHANNEL_MUTES_TABLE = """
CREATE TABLE IF NOT EXISTS channel_mutes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    expire_at TEXT NOT NULL,
    overwrite_snapshot TEXT,
    scope TEXT NOT NULL DEFAULT 'chat_only',
    UNIQUE (guild_id, channel_id, user_id, scope)
);
"""

CREATE_INDEX_EXPIRE_AT = """
CREATE INDEX IF NOT EXISTS idx_channel_mutes_expire_at
ON channel_mutes (expire_at);
"""

CREATE_INDEX_USER = """
CREATE INDEX IF NOT EXISTS idx_channel_mutes_user
ON channel_mutes (guild_id, user_id);
"""

CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""

ALL_MIGRATIONS = (
    CREATE_SCHEMA_VERSION,
    CREATE_CHANNEL_MUTES_TABLE,
    CREATE_INDEX_EXPIRE_AT,
    CREATE_INDEX_USER,
)

# Tables rebuilt (with data reset) when upgrading from an older schema version.
# The mute scope feature changes the channel_mutes unique key, so a clean
# rebuild is used instead of an in-place backfill (see plan).
DROP_CHANNEL_MUTES_TABLE = "DROP TABLE IF EXISTS channel_mutes;"
