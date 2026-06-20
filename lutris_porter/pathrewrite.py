"""Rewrites absolute paths found anywhere inside a YAML/db value tree.

On export, any absolute path that has the game's slug as a path segment
gets the portion up to and including that segment replaced with a fixed
placeholder. On import, the placeholder is swapped back for the new
install location. Paths that don't mention the slug are left alone -
they're not part of the game's own directory and importing can't know
how to fix them anyway.
"""

from collections.abc import Callable
from typing import Any

PathTransform = Callable[[str], str]


def map_strings(value: Any, transform: PathTransform) -> Any:
    """Recursively rebuild value, applying transform to every string leaf."""
    if isinstance(value, dict):
        return {key: map_strings(item, transform) for key, item in value.items()}
    if isinstance(value, list):
        return [map_strings(item, transform) for item in value]
    if isinstance(value, str):
        return transform(value)
    return value


def strip_game_root(path: str, slug: str, placeholder: str) -> str:
    segments = _path_segments(path)
    if segments is None or slug not in segments:
        return path
    index = segments.index(slug)
    remainder = "/".join(segments[index + 1 :])
    return f"{placeholder}/{remainder}" if remainder else placeholder


def restore_game_root(path: str, placeholder: str, new_root: str) -> str:
    return path.replace(placeholder, new_root) if placeholder in path else path


def strip_paths(data: Any, slug: str, placeholder: str) -> Any:
    return map_strings(data, lambda value: strip_game_root(value, slug, placeholder))


def restore_paths(data: Any, new_root: str, placeholder: str) -> Any:
    return map_strings(data, lambda value: restore_game_root(value, placeholder, new_root))


def _path_segments(value: str) -> list[str] | None:
    if not value.startswith("/"):
        return None
    return value.split("/")
