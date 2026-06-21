import tempfile
import unittest
from pathlib import Path

from lutris_porter.paths import ARTWORK_KINDS, LutrisPaths, find_existing_file


class LutrisPathsForHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path("/home/example")
        self.paths = LutrisPaths.for_home(self.home)

    def test_lutris_dir_paths_are_under_local_share_lutris(self) -> None:
        self.assertEqual(self.paths.db_path, self.home / ".local/share/lutris/pga.db")
        self.assertEqual(self.paths.games_config_dir, self.home / ".local/share/lutris/games")
        self.assertEqual(self.paths.banners_dir, self.home / ".local/share/lutris/banners")
        self.assertEqual(self.paths.coverart_dir, self.home / ".local/share/lutris/coverart")
        self.assertEqual(self.paths.system_yml_path, self.home / ".local/share/lutris/system.yml")

    def test_icons_dir_is_under_local_share_icons_not_lutris_dir(self) -> None:
        self.assertEqual(
            self.paths.icons_dir, self.home / ".local/share/icons/hicolor/128x128/apps"
        )

    def test_artwork_dir_resolves_each_kind_to_its_directory(self) -> None:
        for kind in ARTWORK_KINDS:
            with self.subTest(kind=kind.export_name):
                expected = getattr(self.paths, kind.dir_attr)
                self.assertEqual(self.paths.artwork_dir(kind), expected)


class FindExistingFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

    def test_returns_none_when_neither_extension_exists(self) -> None:
        self.assertIsNone(find_existing_file(self.directory, "missing"))

    def test_finds_png_file(self) -> None:
        (self.directory / "game.png").touch()
        self.assertEqual(find_existing_file(self.directory, "game"), self.directory / "game.png")

    def test_finds_jpg_file_when_no_png_present(self) -> None:
        (self.directory / "game.jpg").touch()
        self.assertEqual(find_existing_file(self.directory, "game"), self.directory / "game.jpg")

    def test_prefers_png_over_jpg_when_both_exist(self) -> None:
        (self.directory / "game.png").touch()
        (self.directory / "game.jpg").touch()
        self.assertEqual(find_existing_file(self.directory, "game"), self.directory / "game.png")


if __name__ == "__main__":
    unittest.main()
