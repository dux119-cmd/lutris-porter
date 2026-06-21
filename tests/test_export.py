import tarfile
import unittest

from ._helpers import HAS_ZSTD, ZSTD_SKIP_REASON

if HAS_ZSTD:
    from lutris_porter.export import EXCLUDED_CONFIG_KEYS, _make_game_filter, strip_config_keys


def _dir_info(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = tarfile.DIRTYPE
    return info


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class StripConfigKeysTests(unittest.TestCase):
    def test_removes_an_excluded_top_level_key_and_its_children(self) -> None:
        text = "slug: hades\ngame:\n  exe: hades.exe\n"
        self.assertEqual(strip_config_keys(text), "game:\n  exe: hades.exe\n")

    def test_keeps_keys_not_in_the_excluded_set(self) -> None:
        text = "game:\n  exe: hades.exe\n"
        self.assertEqual(strip_config_keys(text), text)

    def test_removes_every_excluded_key_configured(self) -> None:
        text = "".join(f"{key}: value\n" for key in EXCLUDED_CONFIG_KEYS)
        self.assertEqual(strip_config_keys(text), "")

    def test_blank_line_inside_a_skipped_block_is_also_removed(self) -> None:
        text = "slug: hades\n\ngame:\n  exe: hades.exe\n"
        self.assertEqual(strip_config_keys(text), "game:\n  exe: hades.exe\n")

    def test_blank_line_between_kept_keys_is_preserved(self) -> None:
        text = "game:\n  exe: hades.exe\n\nwine:\n  version: stable\n"
        self.assertEqual(strip_config_keys(text), text)


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class MakeGameFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.filt = _make_game_filter("hades")

    def test_passes_through_members_outside_the_game_prefix(self) -> None:
        info = _dir_info("hades/banner.png")
        self.assertIs(self.filt(info), info)

    def test_keeps_ordinary_game_files(self) -> None:
        info = _dir_info("hades/game/hades.exe")
        self.assertIs(self.filt(info), info)

    def test_excludes_configured_excluded_paths(self) -> None:
        for excluded in ("config_info", "lutris.json", "shadercache", "gstreamer-1.0"):
            with self.subTest(excluded=excluded):
                info = _dir_info(f"hades/game/{excluded}")
                self.assertIsNone(self.filt(info))

    def test_excludes_files_nested_under_an_excluded_directory(self) -> None:
        info = _dir_info("hades/game/shadercache/foo/bar.bin")
        self.assertIsNone(self.filt(info))

    def test_excludes_nested_excluded_path_with_multiple_segments(self) -> None:
        info = _dir_info("hades/game/drive_c/proton_shortcuts/foo.lnk")
        self.assertIsNone(self.filt(info))

    def test_does_not_exclude_a_directory_that_merely_starts_with_an_excluded_name(self) -> None:
        info = _dir_info("hades/game/shadercache2/foo.bin")
        self.assertIs(self.filt(info), info)

    def test_excludes_lowercase_dosdevices_drive_letters_d_through_z(self) -> None:
        for letter in ("d", "m", "z"):
            with self.subTest(letter=letter):
                info = _dir_info(f"hades/game/dosdevices/{letter}:")
                self.assertIsNone(self.filt(info))

    def test_keeps_dosdevices_drive_c(self) -> None:
        info = _dir_info("hades/game/dosdevices/c:")
        self.assertIs(self.filt(info), info)

    def test_keeps_dosdevices_drive_a_and_b(self) -> None:
        for letter in ("a", "b"):
            with self.subTest(letter=letter):
                info = _dir_info(f"hades/game/dosdevices/{letter}:")
                self.assertIs(self.filt(info), info)

    def test_uppercase_drive_letters_are_not_excluded(self) -> None:
        # "d" <= "D" is False, so the lowercase-only range check lets these through.
        info = _dir_info("hades/game/dosdevices/D:")
        self.assertIs(self.filt(info), info)

    def test_keeps_the_dosdevices_directory_entry_itself(self) -> None:
        info = _dir_info("hades/game/dosdevices")
        self.assertIs(self.filt(info), info)


if __name__ == "__main__":
    unittest.main()
