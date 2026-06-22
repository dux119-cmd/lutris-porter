"""Determines where a game is actually installed on disk.

Three sources are tried in order, most explicit first:

1. A manual CLI game directory override path.
2. config.yml's game.exe, when it's an absolute path containing the slug
   as a path segment - everything up to and including that segment.
3. The database's `directory` column, when present.
4. config.yml's game.exe, when it's a *relative* path - in that case
   Lutris installed the game under its global default games directory,
   read from system.yml's system.game_path, at game_path/slug.

Raises if none of these can locate the game.
"""

from pathlib import Path

from .errors import GameDirectoryNotFoundError
from .paths import LutrisPaths


def find_game_root(
    paths: LutrisPaths,
    config_text: str,
    slug: str,
    fallback_directory: str | None,
    game_dir_override: Path | None = None,
) -> Path:
    if game_dir_override is not None:
        return game_dir_override

    root = (
        _root_from_absolute_exe(config_text, slug)
        or fallback_directory
        or _root_from_default_game_path(paths, config_text, slug)
    )
    if root:
        return Path(root)
    raise GameDirectoryNotFoundError(slug)


def read_default_game_path(paths: LutrisPaths) -> str | None:
    if not paths.system_yml_path.exists():
        return None
    try:
        content = paths.system_yml_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if "game_path:" in line:
                parts = line.split("game_path:", 1)
                if len(parts) > 1:
                    val = parts[1].strip().strip("'\"")
                    if val:
                        return val
    except Exception:
        pass
    return None


def _exe_path(config_text: str) -> str | None:
    for line in config_text.splitlines():
        if "exe:" in line:
            parts = line.split("exe:", 1)
            if len(parts) > 1:
                val = parts[1].strip().strip("'\"")
                if val:
                    return val
    return None


def _root_from_absolute_exe(config_text: str, slug: str) -> str | None:
    exe = _exe_path(config_text)
    if not exe or not exe.startswith("/"):
        return None

    segments = exe.split("/")
    if slug not in segments:
        return None

    index = segments.index(slug)
    return "/".join(segments[: index + 1])


def _root_from_default_game_path(
    paths: LutrisPaths, config_text: str, slug: str
) -> str | None:
    exe = _exe_path(config_text)
    if not exe or exe.startswith("/"):
        return None

    default_game_path = read_default_game_path(paths)
    if not default_game_path:
        return None

    return f"{default_game_path.rstrip('/')}/{slug}"
