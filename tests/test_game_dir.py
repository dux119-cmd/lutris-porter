import tempfile
import unittest
from pathlib import Path

from lutris_porter.errors import GameDirectoryNotFoundError
from lutris_porter.game_dir import find_game_root, read_default_game_path
from lutris_porter.paths import LutrisPaths


class GameDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.paths = LutrisPaths.for_home(self.home)

    def write_system_yml(self, content: str) -> None:
        self.paths.system_yml_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.system_yml_path.write_text(content, encoding="utf-8")


class FindGameRootTests(GameDirTestCase):
    def test_override_wins_even_when_config_disagrees(self) -> None:
        override = Path("/explicit/dir")
        config_text = "game:\n  exe: /home/user/Games/hades/hades.exe\n"
        root = find_game_root(self.paths, config_text, "hades", None, game_dir_override=override)
        self.assertEqual(root, override)

    def test_absolute_exe_path_containing_slug_segment(self) -> None:
        config_text = "game:\n  exe: /home/user/Games/hades/hades.exe\n"
        root = find_game_root(self.paths, config_text, "hades", None)
        self.assertEqual(root, Path("/home/user/Games/hades"))

    def test_absolute_exe_takes_priority_over_fallback_directory(self) -> None:
        config_text = "game:\n  exe: /home/user/Games/hades/hades.exe\n"
        root = find_game_root(self.paths, config_text, "hades", "/db/fallback/hades")
        self.assertEqual(root, Path("/home/user/Games/hades"))

    def test_falls_back_to_database_directory_when_exe_has_no_slug_segment(self) -> None:
        config_text = "game:\n  exe: /home/user/Games/other-name/hades.exe\n"
        root = find_game_root(self.paths, config_text, "hades", "/db/fallback/hades")
        self.assertEqual(root, Path("/db/fallback/hades"))

    def test_relative_exe_resolves_under_system_default_game_path(self) -> None:
        self.write_system_yml("system:\n  game_path: '/mnt/games'\n")
        config_text = "game:\n  exe: hades.exe\n"
        root = find_game_root(self.paths, config_text, "hades", None)
        self.assertEqual(root, Path("/mnt/games/hades"))

    def test_raises_when_no_source_can_locate_the_game(self) -> None:
        config_text = "game:\n  exe: hades.exe\n"  # relative, but no system.yml
        with self.assertRaises(GameDirectoryNotFoundError):
            find_game_root(self.paths, config_text, "hades", None)

    def test_does_not_match_slug_as_a_substring_of_a_path_segment(self) -> None:
        config_text = "game:\n  exe: /home/user/Games/hades2/hades.exe\n"
        with self.assertRaises(GameDirectoryNotFoundError):
            find_game_root(self.paths, config_text, "hades", None)


class ReadDefaultGamePathTests(GameDirTestCase):
    def test_returns_none_when_system_yml_missing(self) -> None:
        self.assertIsNone(read_default_game_path(self.paths))

    def test_reads_unquoted_value(self) -> None:
        self.write_system_yml("system:\n  game_path: /mnt/games\n")
        self.assertEqual(read_default_game_path(self.paths), "/mnt/games")

    def test_strips_surrounding_quotes(self) -> None:
        self.write_system_yml("system:\n  game_path: '/mnt/games'\n")
        self.assertEqual(read_default_game_path(self.paths), "/mnt/games")

    def test_returns_none_when_key_is_absent(self) -> None:
        self.write_system_yml("system:\n  other_key: value\n")
        self.assertIsNone(read_default_game_path(self.paths))

    def test_returns_none_instead_of_raising_on_unreadable_path(self) -> None:
        # A directory at system_yml_path exists, but read_text() on it raises -
        # read_default_game_path should swallow that and report "not found".
        self.paths.system_yml_path.mkdir(parents=True)
        self.assertIsNone(read_default_game_path(self.paths))


if __name__ == "__main__":
    unittest.main()
