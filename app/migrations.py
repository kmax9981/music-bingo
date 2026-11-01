"""Creates the tables, then applies the numbered schema changes (PostgreSQL) that create_all() can't make on a table that
already exists. Each change runs once: its id is recorded in schema_migrations, and the changes run in list order inside a
transaction, so a change that fails leaves nothing half-done and is tried again at the next start.

To change an existing table: add ONE new entry at the END of MIGRATIONS (never edit or reorder old ones) and restart.
A brand-new table needs no entry; create_all() makes it."""
import sqlalchemy as sa
from .db import Base, engine
from . import models  # noqa: F401  (the tables to create must be registered before create_all runs; a fresh database has none)


# (id, statements). The first entries come from the older start-up migrations; every statement is safe to run on a
# database that already has the change (IF NOT EXISTS), so databases that predate this list simply record them as done.
MIGRATIONS = [
    ("001_saved_playlists_public_and_per_host", [
        "ALTER TABLE saved_playlists ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE saved_playlists DROP CONSTRAINT IF EXISTS saved_playlists_spotify_playlist_id_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_saved_playlist_owner ON saved_playlists (created_by_user_id, spotify_playlist_id)",
    ]),
    ("002_saved_playlists_explicit_counts", [
        "ALTER TABLE saved_playlists ADD COLUMN IF NOT EXISTS explicit_count INTEGER",
        "ALTER TABLE saved_playlists ADD COLUMN IF NOT EXISTS track_count INTEGER",
        "ALTER TABLE saved_playlists ADD COLUMN IF NOT EXISTS explicit_checked_at TIMESTAMP",
    ]),
    ("003_paper_cards", [
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS is_paper BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS card_number INTEGER",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS paper_venue_id INTEGER",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS paper_join_footer BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS paper_theme VARCHAR(24) NOT NULL DEFAULT ''",
    ]),
    ("004_saved_games_hints_room", [
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS is_saved BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS sessions_played INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS last_played_at TIMESTAMP",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS hint_mode VARCHAR(8) NOT NULL DEFAULT 'off'",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS room_reveal BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS room_sound BOOLEAN NOT NULL DEFAULT FALSE",
    ]),
    ("005_host_theme", [
        "ALTER TABLE host_users ADD COLUMN IF NOT EXISTS theme VARCHAR(24) NOT NULL DEFAULT 'midnight'",
    ]),
    ("006_custom_theme", [   # the host's own colors; a paper game remembers them as 'custom:RRGGBB-RRGGBB-RRGGBB' (30 characters)
        "ALTER TABLE host_users ADD COLUMN IF NOT EXISTS custom_colors VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE games ALTER COLUMN paper_theme TYPE VARCHAR(40)",
    ]),
    ("007_must_change_password", [
        "ALTER TABLE host_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE",
    ]),
    ("008_indexes", [   # lookups that every game page makes and that had no index
        "CREATE INDEX IF NOT EXISTS ix_games_owner_key ON games (owner_key)",
        "CREATE INDEX IF NOT EXISTS ix_bingo_claims_game_id ON bingo_claims (game_id)",
        "CREATE INDEX IF NOT EXISTS ix_bingo_claims_player_id ON bingo_claims (player_id)",
    ]),
    ("009_venues_renamed_events", [   # the saved "venues" are now "events" (create_all has just made an empty events table on an old database; a new database already has the new names)
        """DO $$ BEGIN
            IF to_regclass('venues') IS NOT NULL THEN
                IF to_regclass('events') IS NOT NULL THEN DROP TABLE events; END IF;
                ALTER TABLE venues RENAME TO events;
                ALTER SEQUENCE IF EXISTS venues_id_seq RENAME TO events_id_seq;
                ALTER INDEX IF EXISTS venues_pkey RENAME TO events_pkey;
                ALTER INDEX IF EXISTS ix_venues_host_user_id RENAME TO ix_events_host_user_id;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'games' AND column_name = 'paper_venue_id') THEN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'games' AND column_name = 'event_id') THEN
                    ALTER TABLE games DROP COLUMN paper_venue_id;
                ELSE
                    ALTER TABLE games RENAME COLUMN paper_venue_id TO event_id;
                END IF;
            END IF;
        END $$""",
    ]),
    ("010_win_patterns", [
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS win_pattern VARCHAR(10) NOT NULL DEFAULT 'line'",
        "ALTER TABLE bingo_claims ADD COLUMN IF NOT EXISTS pattern VARCHAR(10) NOT NULL DEFAULT 'line'",
    ]),
    ("011_cohost_link", [
        "ALTER TABLE games ADD COLUMN IF NOT EXISTS cohost_token VARCHAR(32)",
    ]),
    ("012_player_avatars", [
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS avatar VARCHAR(16) NOT NULL DEFAULT ''",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS avatar_color VARCHAR(10) NOT NULL DEFAULT ''",
    ]),
]

_LOCK_KEY = 7420311   # one app process at a time runs the list


def run_migrations(eng, migrations):
    """Apply the entries not yet recorded in schema_migrations, in order. Returns the ids applied now."""
    applied_now = []
    with eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE IF NOT EXISTS schema_migrations (id VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
    for mid, statements in migrations:
        with eng.begin() as conn:
            if eng.dialect.name == 'postgresql':
                conn.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})   # held until this change commits
            if conn.execute(sa.text("SELECT 1 FROM schema_migrations WHERE id = :i"), {"i": mid}).first():
                continue
            for stmt in statements:
                conn.execute(sa.text(stmt))
            conn.execute(sa.text("INSERT INTO schema_migrations (id) VALUES (:i)"), {"i": mid})
            applied_now.append(mid)
            print(f"MIGRATION applied {mid}")
    return applied_now


Base.metadata.create_all(bind=engine)
if engine.dialect.name == 'postgresql':   # local test copies (SQLite) are created fresh with the current schema
    run_migrations(engine, MIGRATIONS)
