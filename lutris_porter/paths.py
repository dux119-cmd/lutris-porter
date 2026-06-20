"""Knows where Lutris keeps things on disk. Nothing here touches the
database or YAML content - just paths.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

GAME_ROOT_PLACEHOLDER = "{{LUTRIS_GAME_ROOT}}"
ARTWORK_EXTENSIONS = ("png", "jpg")


class ArtworkKind(NamedTuple):
    export_name: str  # filename used inside the tarball, e.g. "banner"
    dir_attr: str  # attribute name on LutrisPaths pointing at the on-disk dir
    stem: str  # on-disk filename stem, with a "{slug}" placeholder


ARTWORK_KINDS = (
    ArtworkKind(export_name="banner", dir_attr="banners_dir", stem="{slug}"),
    ArtworkKind(export_name="coverart", dir_attr="coverart_dir", stem="{slug}"),
    ArtworkKind(export_name="logo", dir_attr="icons_dir", stem="lutris_{slug}"),
)


@dataclass(frozen=True)
class LutrisPaths:
    db_path: Path
    games_config_dir: Path
    banners_dir: Path
    coverart_dir: Path
    icons_dir: Path
    system_yml_path: Path

    @staticmethod
    def for_home(home: Path) -> "LutrisPaths":
        lutris_dir = home / ".local/share/lutris"
        return LutrisPaths(
            db_path=lutris_dir / "pga.db",
            games_config_dir=lutris_dir / "games",
            banners_dir=lutris_dir / "banners",
            coverart_dir=lutris_dir / "coverart",
            icons_dir=home / ".local/share/icons/hicolor/128x128/apps",
            system_yml_path=lutris_dir / "system.yml",
        )

    def artwork_dir(self, kind: ArtworkKind) -> Path:
        return getattr(self, kind.dir_attr)


def find_existing_file(directory: Path, stem: str) -> Path | None:
    """Find <directory>/<stem>.png or .jpg - whichever exists."""
    for extension in ARTWORK_EXTENSIONS:
        candidate = directory / f"{stem}.{extension}"
        if candidate.exists():
            return candidate
    return None
