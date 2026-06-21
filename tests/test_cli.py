import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from lutris_porter.errors import GameNotFoundError
from lutris_porter.paths import LutrisPaths

from ._helpers import HAS_ZSTD, ZSTD_SKIP_REASON

if HAS_ZSTD:
    from lutris_porter.cli import _dispatch, build_parser, main
    from lutris_porter.zstd_io import DEFAULT_WINDOW_LOG


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class BuildParserDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_no_arguments_means_no_command_and_list_games_false(self) -> None:
        args = self.parser.parse_args([])
        self.assertFalse(args.list_games)
        self.assertIsNone(args.command)

    def test_list_flag_sets_list_games(self) -> None:
        for flag in ("-l", "--list"):
            with self.subTest(flag=flag):
                args = self.parser.parse_args([flag])
                self.assertTrue(args.list_games)


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class BuildParserExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_required_arguments_and_defaults(self) -> None:
        args = self.parser.parse_args(["export", "hades", "/out"])
        self.assertEqual(args.command, "export")
        self.assertEqual(args.slug, "hades")
        self.assertEqual(args.target_dir, Path("/out"))
        self.assertIsNone(args.game_dir)

    def test_optional_flags_override_defaults(self) -> None:
        args = self.parser.parse_args(
            [
                "export",
                "hades",
                "/out",
                "--game-dir",
                "/custom",
                "--zstd-level",
                "1",
                "--zstd-window-log",
                "20",
            ]
        )
        self.assertEqual(args.game_dir, Path("/custom"))
        self.assertEqual(args.zstd_level, 1)
        self.assertEqual(args.zstd_window_log, 20)

    def test_target_dir_expands_user_home(self) -> None:
        with patch.dict(os.environ, {"HOME": "/custom/home"}):
            args = self.parser.parse_args(["export", "hades", "~/out"])
        self.assertEqual(args.target_dir, Path("/custom/home/out"))


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class BuildParserImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_parses_tarball_and_target_dir(self) -> None:
        args = self.parser.parse_args(["import", "https://example.com/hades.tar.zst", "/install"])
        self.assertEqual(args.command, "import")
        self.assertEqual(args.tarball, "https://example.com/hades.tar.zst")
        self.assertEqual(args.target_dir, Path("/install"))

    def test_tarball_is_left_as_a_plain_string_not_expanded(self) -> None:
        # Local-path expansion happens inside importer._open_source, not here.
        args = self.parser.parse_args(["import", "~/hades.tar.zst", "/install"])
        self.assertEqual(args.tarball, "~/hades.tar.zst")


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()
        self.paths = LutrisPaths.for_home(Path("/unused"))

    def parse(self, argv: list[str]):
        return self.parser.parse_args(argv)

    def test_list_flag_prints_slugs_from_the_database(self) -> None:
        with patch("lutris_porter.cli.connect"), patch(
            "lutris_porter.cli.list_slugs", return_value=["celeste", "hades"]
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                _dispatch(self.parser, self.paths, self.parse(["--list"]))
        self.assertEqual(out.getvalue(), "celeste\nhades\n")

    def test_export_command_calls_export_game_with_parsed_arguments(self) -> None:
        with patch(
            "lutris_porter.cli.export_game", return_value=Path("/out/hades.tar.zst")
        ) as mock_export:
            out = io.StringIO()
            with redirect_stdout(out):
                _dispatch(
                    self.parser,
                    self.paths,
                    self.parse(["export", "hades", "/out", "--zstd-level", "3"]),
                )
        mock_export.assert_called_once_with(
            self.paths,
            "hades",
            Path("/out"),
            compression_level=3,
            window_log=DEFAULT_WINDOW_LOG,
            game_dir_override=None,
        )
        self.assertIn("Exported 'hades' to /out/hades.tar.zst", out.getvalue())

    def test_import_command_calls_import_game_with_parsed_arguments(self) -> None:
        with patch("lutris_porter.cli.import_game", return_value="hades") as mock_import:
            out = io.StringIO()
            with redirect_stdout(out):
                _dispatch(
                    self.parser,
                    self.paths,
                    self.parse(["import", "/tmp/hades.tar.zst", "/install"]),
                )
        mock_import.assert_called_once_with(self.paths, "/tmp/hades.tar.zst", Path("/install"))
        self.assertIn("Imported 'hades'", out.getvalue())

    def test_no_command_prints_help(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            _dispatch(self.parser, self.paths, self.parse([]))
        self.assertIn("usage:", out.getvalue())


@unittest.skipUnless(HAS_ZSTD, ZSTD_SKIP_REASON)
class MainErrorHandlingTests(unittest.TestCase):
    def test_lutris_porter_error_is_caught_and_reported_with_exit_code_1(self) -> None:
        with patch("lutris_porter.cli.export_game", side_effect=GameNotFoundError("hades")):
            err = io.StringIO()
            with tempfile.TemporaryDirectory() as out_dir, patch("sys.stderr", err):
                exit_code = main(["export", "hades", out_dir])
        self.assertEqual(exit_code, 1)
        self.assertIn("Error: No game found with slug 'hades'", err.getvalue())

    def test_successful_command_returns_zero(self) -> None:
        with patch("lutris_porter.cli.connect"), patch(
            "lutris_porter.cli.list_slugs", return_value=[]
        ):
            self.assertEqual(main(["--list"]), 0)


if __name__ == "__main__":
    unittest.main()
