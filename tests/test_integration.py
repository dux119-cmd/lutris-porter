"""Round-trips export_game -> import_game through a real (but tiny) fake
Lutris install, exercising the full primary workflow end to end: db row,
config.yml rewriting, artwork, and the game/ directory tar filter - all
through real zstd compression.
"""

import tempfile
import unittest
from pathlib import Path

from lutris_porter.db import connect, insert_game
from lutris_porter.errors import InstalledSlugAlreadyExistsError
from lutris_porter.paths import LutrisPaths

from ._helpers import HAS_ZSTD, ZSTD_SKIP_REASON, init_games_db

if HAS_ZSTD:
    from lutris_porter.export import export_game
    from lutris_porter.importer import import_game


def _make_lutris_home(home: Path) -> LutrisPaths:
    paths = LutrisPaths.for_home(home)
    paths.games_config_dir.mkdir(parents=True, exist_ok=True)
    init_games_db(paths.db_path)
    return paths


def _write_game_files(game_root: Path) -> None:
    (game_root / "drive_c").mkdir(parents=True)
    (game_root / "hades.exe").write_text("binary-stand-in")
    (game_root / "saves").mkdir()
    (game_root / "saves" / "slot1.dat").write_text("save data")
    (game_root / "shadercache").mkdir()
    (game_root / "shadercache" / "junk.bin").write_text("regenerable cache")
    (game_root / "dosdevices").mkdir()
    (game_root / "dosdevices" / "c:").symlink_to(game_root / "drive_c")
    (game_root / "dosdevices" / "d:").symlink_to("/dev/null")


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class ExportImportRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

        self.export_paths = _make_lutris_home(self.tmp_path / "export_home")
        self.game_root = self.tmp_path / "Games" / "hades"
        _write_game_files(self.game_root)

        config_text = (
            "slug: hades\n"
            "game_slug: hades\n"
            "name: Hades\n"
            "script: ignored\n"
            "game:\n"
            f"  exe: {self.game_root}/hades.exe\n"
        )
        (self.export_paths.games_config_dir / "hades.yml").write_text(config_text)

        banner_dir = self.export_paths.banners_dir
        banner_dir.mkdir(parents=True, exist_ok=True)
        (banner_dir / "hades.png").write_bytes(b"PNGDATA")

        with connect(self.export_paths.db_path) as connection:
            insert_game(
                connection,
                {
                    "slug": "hades",
                    "name": "Hades",
                    "configpath": "hades",
                    "directory": None,
                    "installed": 1,
                    "installed_at": 1_600_000_000,
                    "lastplayed": 1_600_000_500,
                    "playtime": 12.5,
                },
            )

        self.export_dir = self.tmp_path / "exported"
        self.tarball = export_game(self.export_paths, "hades", self.export_dir)

    def test_export_produces_a_tarball(self) -> None:
        self.assertTrue(self.tarball.is_file())
        self.assertEqual(self.tarball.name, "hades.tar.zst")

    def test_import_into_a_fresh_install_restores_everything(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"

        slug = import_game(import_paths, self.tarball, install_target)

        self.assertEqual(slug, "hades")
        installed_root = install_target / "hades"
        self.assertEqual((installed_root / "hades.exe").read_text(), "binary-stand-in")
        self.assertEqual((installed_root / "saves" / "slot1.dat").read_text(), "save data")

    def test_import_excludes_shadercache_and_lettered_dosdevices(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"
        import_game(import_paths, self.tarball, install_target)

        installed_root = install_target / "hades"
        self.assertFalse((installed_root / "shadercache").exists())
        self.assertFalse((installed_root / "dosdevices" / "d:").exists())

    def test_import_keeps_dosdevices_drive_c(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"
        import_game(import_paths, self.tarball, install_target)

        self.assertTrue((install_target / "hades" / "dosdevices" / "c:").is_symlink())

    def test_import_rewrites_config_exe_to_the_new_install_root(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"
        import_game(import_paths, self.tarball, install_target)

        config_text = (import_paths.games_config_dir / "hades.yml").read_text()
        self.assertIn(f"exe: {install_target / 'hades'}/hades.exe", config_text)
        self.assertNotIn("{{LUTRIS_GAME_ROOT}}", config_text)

    def test_import_strips_excluded_config_keys(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"
        import_game(import_paths, self.tarball, install_target)

        config_text = (import_paths.games_config_dir / "hades.yml").read_text()
        self.assertNotIn("script:", config_text)
        self.assertNotIn("name:", config_text)

    def test_import_restores_artwork(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"
        import_game(import_paths, self.tarball, install_target)

        self.assertEqual((import_paths.banners_dir / "hades.png").read_bytes(), b"PNGDATA")

    def test_import_resets_playtime_and_lastplayed_in_the_database(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"
        import_game(import_paths, self.tarball, install_target)

        with connect(import_paths.db_path) as connection:
            row = connection.execute("SELECT * FROM games WHERE slug = 'hades'").fetchone()
        self.assertEqual(row["playtime"], 0)
        self.assertIsNone(row["lastplayed"])
        self.assertEqual(row["name"], "Hades")

    def test_reimporting_into_an_install_where_the_slug_already_exists_raises(self) -> None:
        import_paths = _make_lutris_home(self.tmp_path / "import_home")
        install_target = self.tmp_path / "install"
        import_game(import_paths, self.tarball, install_target)

        # The exported row carries installed=1 through, so a second import
        # against the same db is rejected as "already installed" rather than
        # "destination exists" (which only applies to slugs with no db row).
        with self.assertRaises(InstalledSlugAlreadyExistsError):
            import_game(import_paths, self.tarball, install_target)


if __name__ == "__main__":
    unittest.main()
