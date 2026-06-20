"""All access to pga.db. Rows are plain dicts - no ORM, no model class,
just what sqlite3 already gives us.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def list_slugs(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute("SELECT slug FROM games ORDER BY slug").fetchall()
    return [row["slug"] for row in rows]


def find_game_by_slug(connection: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM games WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def slug_exists(connection: sqlite3.Connection, slug: str) -> bool:
    return find_game_by_slug(connection, slug) is not None


def insert_game(connection: sqlite3.Connection, game: dict[str, Any]) -> int:
    columns = ", ".join(game.keys())
    placeholders = ", ".join("?" for _ in game)
    cursor = connection.execute(
        f"INSERT OR REPLACE INTO games ({columns}) VALUES ({placeholders})",
        tuple(game.values()),
    )
    connection.commit()
    return cursor.lastrowid
