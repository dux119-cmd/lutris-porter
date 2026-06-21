import sqlite3
import tempfile
import unittest
from pathlib import Path

from lutris_porter.db import connect, find_game_by_slug, insert_game, list_slugs

from ._helpers import init_games_db


class DbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "pga.db"
        init_games_db(self.db_path)


class ConnectTests(DbTestCase):
    def test_yields_a_connection_with_row_factory_set(self) -> None:
        with connect(self.db_path) as connection:
            self.assertIsInstance(connection, sqlite3.Connection)
            self.assertIs(connection.row_factory, sqlite3.Row)

    def test_closes_connection_on_exit(self) -> None:
        with connect(self.db_path) as connection:
            pass
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_closes_connection_even_when_block_raises(self) -> None:
        with self.assertRaises(ValueError):
            with connect(self.db_path) as connection:
                raise ValueError("boom")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


class ListSlugsTests(DbTestCase):
    def test_returns_empty_list_when_no_games(self) -> None:
        with connect(self.db_path) as connection:
            self.assertEqual(list_slugs(connection), [])

    def test_returns_slugs_sorted_alphabetically(self) -> None:
        with connect(self.db_path) as connection:
            for slug in ("zelda", "celeste", "hades"):
                insert_game(connection, {"slug": slug})
            self.assertEqual(list_slugs(connection), ["celeste", "hades", "zelda"])


class FindGameBySlugTests(DbTestCase):
    def test_returns_none_when_slug_missing(self) -> None:
        with connect(self.db_path) as connection:
            self.assertIsNone(find_game_by_slug(connection, "missing"))

    def test_returns_row_as_dict_when_present(self) -> None:
        with connect(self.db_path) as connection:
            insert_game(connection, {"slug": "hades", "name": "Hades"})
            game = find_game_by_slug(connection, "hades")
        self.assertEqual(game["slug"], "hades")
        self.assertEqual(game["name"], "Hades")


class InsertGameTests(DbTestCase):
    def test_returns_lastrowid_of_inserted_row(self) -> None:
        with connect(self.db_path) as connection:
            row_id = insert_game(connection, {"slug": "hades"})
        self.assertIsInstance(row_id, int)

    def test_insert_or_replace_overwrites_existing_row_for_same_slug(self) -> None:
        with connect(self.db_path) as connection:
            insert_game(connection, {"slug": "hades", "name": "Hades"})
            insert_game(connection, {"slug": "hades", "name": "Hades II"})
            game = find_game_by_slug(connection, "hades")
        self.assertEqual(game["name"], "Hades II")

    def test_commits_so_data_is_visible_on_a_new_connection(self) -> None:
        with connect(self.db_path) as connection:
            insert_game(connection, {"slug": "hades"})
        with connect(self.db_path) as connection:
            self.assertEqual(list_slugs(connection), ["hades"])


if __name__ == "__main__":
    unittest.main()
