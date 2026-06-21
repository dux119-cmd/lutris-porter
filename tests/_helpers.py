"""Shared fixtures for the lutris_porter test suite.

Leading underscore keeps this out of unittest's default `test*` discovery.
"""

import sqlite3
from pathlib import Path

try:
    from compression import zstd  # noqa: F401  (presence check only)

    HAS_ZSTD = True
except ModuleNotFoundError:
    HAS_ZSTD = False

ZSTD_SKIP_REASON = "requires Python 3.14's compression.zstd module"

# Mirrors the subset of pga.db's `games` table that lutris_porter reads/writes.
GAMES_TABLE_DDL = """
CREATE TABLE games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE,
    name TEXT,
    configpath TEXT,
    directory TEXT,
    installed INTEGER,
    installed_at INTEGER,
    lastplayed INTEGER,
    playtime REAL
)
"""


def init_games_db(db_path: Path) -> None:
    """Create an empty `games` table at db_path."""
    with sqlite3.connect(db_path) as connection:
        connection.execute(GAMES_TABLE_DDL)
