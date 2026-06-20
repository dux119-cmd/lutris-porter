"""Domain errors. The CLI catches LutrisPorterError and prints a clean message;
anything else is an unexpected bug and is left to surface as a traceback.
"""

from pathlib import Path


class LutrisPorterError(Exception):
    """Base error for all expected lutris-porter failures."""


class GameNotFoundError(LutrisPorterError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"No game found with slug '{slug}'")


class ConfigNotFoundError(LutrisPorterError):
    def __init__(self, path: Path) -> None:
        super().__init__(f"Config file not found: {path}")


class GameDirectoryNotFoundError(LutrisPorterError):
    def __init__(self, slug: str) -> None:
        super().__init__(
            f"Could not determine the install directory for '{slug}' "
            "(checked config.yml's game.exe and the database's directory column)"
        )


class InstalledSlugAlreadyExistsError(LutrisPorterError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"A game with slug '{slug}' is already installed in the database")


class DestinationExistsError(LutrisPorterError):
    def __init__(self, path: Path) -> None:
        super().__init__(f"Destination already exists: {path}")


class InvalidCompressionSettingError(LutrisPorterError):
    def __init__(
        self, name: str, value: int, lower: int, upper: int, zero_means_auto: bool = False
    ) -> None:
        auto_note = " (or 0 for automatic)" if zero_means_auto else ""
        super().__init__(f"Invalid {name} {value}: must be between {lower} and {upper}{auto_note}")
