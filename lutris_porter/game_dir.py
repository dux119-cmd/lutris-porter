"""Determines where a game is actually installed on disk.

Three sources are tried in order, most explicit first:

1. config.yml's game.exe, when it's an absolute path containing the slug
   as a path segment - everything up to and including that segment.
2. The database's `directory` column, when present.
3. config.yml's game.exe, when it's a *relative* path - in that case
   Lutris installed the game under its global default games directory,
   read from system.yml's system.game_path, at game_path/slug.

Raises if none of these can locate the game.
"""

from pathlib import Path
from typing import Any

from .errors import GameDirectoryNotFoundError
from .paths import LutrisPaths
from .yaml_io import load_yaml


def find_game_root(
    paths: LutrisPaths, config: dict[str, Any], slug: str, fallback_directory: str | None
) -> Path:
    root = (
        _root_from_absolute_exe(config, slug)
        or fallback_directory
        or _root_from_default_game_path(paths, config, slug)
    )
    if root:
        return Path(root)
    raise GameDirectoryNotFoundError(slug)


def read_default_game_path(paths: LutrisPaths) -> str | None:
    if not paths.system_yml_path.exists():
        return None
    system_config = load_yaml(paths.system_yml_path)
    system_section = system_config.get("system")
    game_path = system_section.get("game_path") if isinstance(system_section, dict) else None
    return game_path if isinstance(game_path, str) and game_path else None


def _exe_path(config: dict[str, Any]) -> str | None:
    game_section = config.get("game")
    exe = game_section.get("exe") if isinstance(game_section, dict) else None
    return exe if isinstance(exe, str) and exe else None


def _root_from_absolute_exe(config: dict[str, Any], slug: str) -> str | None:
    exe = _exe_path(config)
    if not exe or not exe.startswith("/"):
        return None

    segments = exe.split("/")
    if slug not in segments:
        return None

    index = segments.index(slug)
    return "/".join(segments[: index + 1])


def _root_from_default_game_path(paths: LutrisPaths, config: dict[str, Any], slug: str) -> str | None:
    exe = _exe_path(config)
    if not exe or exe.startswith("/"):
        return None

    default_game_path = read_default_game_path(paths)
    if not default_game_path:
        return None

    return f"{default_game_path.rstrip('/')}/{slug}"
