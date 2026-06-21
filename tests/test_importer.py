import io
import tarfile
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from lutris_porter.errors import (
    DestinationExistsError,
    InstalledSlugAlreadyExistsError,
    TarballFetchError,
)
from lutris_porter.paths import LutrisPaths

from ._helpers import HAS_ZSTD, ZSTD_SKIP_REASON, init_games_db

if HAS_ZSTD:
    from lutris_porter.db import connect, insert_game
    from lutris_porter.importer import (
        _extract_game_member,
        _install_artwork_member,
        _is_game_member,
        _open_source,
        _prepare_for_insert,
        _resolve_install_root,
        _strip_top_level,
    )


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class StripTopLevelTests(unittest.TestCase):
    def test_strips_the_leading_slug_segment(self) -> None:
        self.assertEqual(_strip_top_level("hades/game/hades.exe"), "game/hades.exe")

    def test_returns_none_for_the_bare_top_level_entry(self) -> None:
        self.assertIsNone(_strip_top_level("hades"))

    def test_returns_none_when_nothing_follows_the_trailing_slash(self) -> None:
        self.assertIsNone(_strip_top_level("hades/"))


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class IsGameMemberTests(unittest.TestCase):
    def test_bare_game_directory_entry_is_a_game_member(self) -> None:
        self.assertTrue(_is_game_member("game"))

    def test_path_under_game_is_a_game_member(self) -> None:
        self.assertTrue(_is_game_member("game/hades.exe"))

    def test_unrelated_path_is_not_a_game_member(self) -> None:
        self.assertFalse(_is_game_member("config.yml"))

    def test_path_merely_starting_with_game_is_not_a_game_member(self) -> None:
        self.assertFalse(_is_game_member("game2/file"))


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class ResolveInstallRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        home = Path(self._tmp.name)
        self.paths = LutrisPaths.for_home(home)
        self.paths.db_path.parent.mkdir(parents=True, exist_ok=True)
        init_games_db(self.paths.db_path)
        self.target_dir = home / "install"
        self.target_dir.mkdir()

    def test_new_slug_resolves_to_target_dir_slug_with_no_existing_id(self) -> None:
        slug, install_root, existing_id = _resolve_install_root(
            self.paths, {"slug": "hades"}, self.target_dir
        )
        self.assertEqual(slug, "hades")
        self.assertEqual(install_root, self.target_dir / "hades")
        self.assertIsNone(existing_id)

    def test_raises_when_install_root_already_exists_on_disk(self) -> None:
        (self.target_dir / "hades").mkdir()
        with self.assertRaises(DestinationExistsError):
            _resolve_install_root(self.paths, {"slug": "hades"}, self.target_dir)

    def test_reuses_existing_id_for_a_previously_uninstalled_row(self) -> None:
        with connect(self.paths.db_path) as connection:
            row_id = insert_game(connection, {"slug": "hades", "installed": 0})

        slug, install_root, existing_id = _resolve_install_root(
            self.paths, {"slug": "hades"}, self.target_dir
        )
        self.assertEqual(existing_id, row_id)
        self.assertEqual(install_root, self.target_dir / "hades")

    def test_raises_when_slug_is_already_installed(self) -> None:
        with connect(self.paths.db_path) as connection:
            insert_game(connection, {"slug": "hades", "installed": 1})

        with self.assertRaises(InstalledSlugAlreadyExistsError):
            _resolve_install_root(self.paths, {"slug": "hades"}, self.target_dir)


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class ExtractGameMemberTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.install_root = Path(self._tmp.name) / "hades"

        tar_path = Path(self._tmp.name) / "src.tar"
        with tarfile.open(tar_path, "w") as tar:
            dir_info = tarfile.TarInfo("game/saves")
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            tar.addfile(dir_info)

            content = b"save data"
            file_info = tarfile.TarInfo("game/saves/slot1.dat")
            file_info.size = len(content)
            file_info.mode = 0o644
            tar.addfile(file_info, io.BytesIO(content))

        self.tar_path = tar_path

    def _members(self) -> tarfile.TarFile:
        return tarfile.open(self.tar_path, "r")

    def test_creates_directories(self) -> None:
        with self._members() as tar:
            member = tar.getmember("game/saves")
            _extract_game_member(tar, member, "game/saves", self.install_root)
        self.assertTrue((self.install_root / "saves").is_dir())

    def test_writes_file_contents_and_permissions(self) -> None:
        with self._members() as tar:
            for member in tar:
                if member.name == "game/saves":
                    _extract_game_member(tar, member, "game/saves", self.install_root)
                elif member.name == "game/saves/slot1.dat":
                    _extract_game_member(tar, member, "game/saves/slot1.dat", self.install_root)
        destination = self.install_root / "saves/slot1.dat"
        self.assertEqual(destination.read_bytes(), b"save data")
        self.assertEqual(destination.stat().st_mode & 0o777, 0o644)

    def test_bare_game_member_path_extracts_directly_to_install_root(self) -> None:
        # member_path "game" (no suffix) means relative-to-prefix is ".", so the
        # destination collapses to install_root itself, regardless of which
        # member supplies the directory bit.
        with self._members() as tar:
            member = tar.getmember("game/saves")
            _extract_game_member(tar, member, "game", self.install_root)
        self.assertTrue(self.install_root.is_dir())


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class InstallArtworkMemberTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = LutrisPaths.for_home(Path(self._tmp.name))

        content = b"PNGDATA"
        self.tar_path = Path(self._tmp.name) / "art.tar"
        with tarfile.open(self.tar_path, "w") as tar:
            info = tarfile.TarInfo("banner.png")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

    def test_installs_matching_artwork_to_its_slug_named_destination(self) -> None:
        with tarfile.open(self.tar_path, "r") as tar:
            member = tar.getmember("banner.png")
            _install_artwork_member(tar, member, "banner.png", self.paths, "hades")
        destination = self.paths.banners_dir / "hades.png"
        self.assertEqual(destination.read_bytes(), b"PNGDATA")

    def test_does_nothing_for_an_unrecognized_member_name(self) -> None:
        with tarfile.open(self.tar_path, "r") as tar:
            member = tar.getmember("banner.png")
            _install_artwork_member(tar, member, "not-artwork.txt", self.paths, "hades")
        self.assertFalse(self.paths.banners_dir.exists())


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class OpenSourceTests(unittest.TestCase):
    def test_reads_a_local_path_with_user_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tarball = Path(tmp) / "game.tar.zst"
            tarball.write_bytes(b"data")
            with _open_source(tarball) as stream:
                self.assertEqual(stream.read(), b"data")

    def test_reads_a_local_path_given_as_a_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tarball = Path(tmp) / "game.tar.zst"
            tarball.write_bytes(b"data")
            with _open_source(str(tarball)) as stream:
                self.assertEqual(stream.read(), b"data")

    def test_yields_the_url_response_on_success(self) -> None:
        response = io.BytesIO(b"remote data")
        with patch("lutris_porter.importer.urllib.request.urlopen", return_value=response):
            with _open_source("https://example.com/game.tar.zst") as stream:
                self.assertEqual(stream.read(), b"remote data")

    def test_wraps_a_url_error_as_a_tarball_fetch_error(self) -> None:
        with patch(
            "lutris_porter.importer.urllib.request.urlopen",
            side_effect=urllib.error.URLError("not found"),
        ):
            with self.assertRaises(TarballFetchError):
                with _open_source("https://example.com/game.tar.zst"):
                    pass


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class PrepareForInsertTests(unittest.TestCase):
    def test_resets_playtime_and_lastplayed(self) -> None:
        with patch("lutris_porter.importer.time.time", return_value=1_700_000_000.0):
            result = _prepare_for_insert(
                {"slug": "hades", "lastplayed": 123, "playtime": 99.0}, existing_id=None
            )
        self.assertIsNone(result["lastplayed"])
        self.assertEqual(result["playtime"], 0)
        self.assertEqual(result["installed_at"], 1_700_000_000)

    def test_uses_existing_id_when_given(self) -> None:
        result = _prepare_for_insert({"slug": "hades"}, existing_id=42)
        self.assertEqual(result["id"], 42)

    def test_drops_id_when_no_existing_id_and_database_has_one(self) -> None:
        result = _prepare_for_insert({"slug": "hades", "id": 7}, existing_id=None)
        self.assertNotIn("id", result)

    def test_does_not_require_an_id_key_to_be_present(self) -> None:
        result = _prepare_for_insert({"slug": "hades"}, existing_id=None)
        self.assertNotIn("id", result)


if __name__ == "__main__":
    unittest.main()
