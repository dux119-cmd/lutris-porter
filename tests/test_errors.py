import unittest
from pathlib import Path

from lutris_porter.errors import (
    ConfigNotFoundError,
    DestinationExistsError,
    GameDirectoryNotFoundError,
    GameNotFoundError,
    InstalledSlugAlreadyExistsError,
    InvalidCompressionSettingError,
    LutrisPorterError,
    TarballFetchError,
)


class ErrorHierarchyTests(unittest.TestCase):
    def test_all_domain_errors_are_lutris_porter_errors(self) -> None:
        error_classes = (
            GameNotFoundError,
            ConfigNotFoundError,
            GameDirectoryNotFoundError,
            InstalledSlugAlreadyExistsError,
            DestinationExistsError,
            InvalidCompressionSettingError,
            TarballFetchError,
        )
        for error_class in error_classes:
            with self.subTest(error_class=error_class.__name__):
                self.assertTrue(issubclass(error_class, LutrisPorterError))


class ErrorMessageTests(unittest.TestCase):
    def test_game_not_found_includes_slug(self) -> None:
        self.assertEqual(str(GameNotFoundError("hades")), "No game found with slug 'hades'")

    def test_config_not_found_includes_path(self) -> None:
        path = Path("/some/config.yml")
        self.assertEqual(str(ConfigNotFoundError(path)), f"Config file not found: {path}")

    def test_game_directory_not_found_includes_slug_and_hint(self) -> None:
        message = str(GameDirectoryNotFoundError("hades"))
        self.assertIn("hades", message)
        self.assertIn("--game-dir", message)

    def test_installed_slug_already_exists_includes_slug(self) -> None:
        message = str(InstalledSlugAlreadyExistsError("hades"))
        self.assertIn("hades", message)
        self.assertIn("already installed", message)

    def test_destination_exists_includes_path(self) -> None:
        path = Path("/install/hades")
        self.assertEqual(str(DestinationExistsError(path)), f"Destination already exists: {path}")

    def test_tarball_fetch_error_includes_url_and_reason(self) -> None:
        message = str(TarballFetchError("https://example.com/g.tar.zst", "timed out"))
        self.assertIn("https://example.com/g.tar.zst", message)
        self.assertIn("timed out", message)


class InvalidCompressionSettingErrorTests(unittest.TestCase):
    def test_message_without_auto_note(self) -> None:
        message = str(InvalidCompressionSettingError("compression level", 99, 1, 22))
        self.assertEqual(message, "Invalid compression level 99: must be between 1 and 22")

    def test_message_with_auto_note(self) -> None:
        message = str(
            InvalidCompressionSettingError("window log", 99, 10, 31, zero_means_auto=True)
        )
        self.assertEqual(
            message, "Invalid window log 99: must be between 10 and 31 (or 0 for automatic)"
        )


if __name__ == "__main__":
    unittest.main()
