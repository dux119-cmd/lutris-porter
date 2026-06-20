"""Streams a game's files, database row, config, and artwork straight into
a zstd-compressed tarball. Nothing is staged or copied to a temporary
location first - source files are read once and written once, which
matters when a game install is tens of gigabytes.

Member order inside the tarball is deliberate: database.json first, then
config.yml and artwork, then the (potentially huge) game/ directory last.
The importer relies on this order to extract game/ directly to its final
destination in a single streaming pass.
"""

import io
import json
import tarfile
from pathlib import Path
from typing import Any

from .db import connect, find_game_by_slug
from .errors import ConfigNotFoundError, GameNotFoundError
from .game_dir import find_game_root
from .pathrewrite import strip_paths
from .paths import ARTWORK_KINDS, GAME_ROOT_PLACEHOLDER, LutrisPaths, find_existing_file
from .zstd_io import (
    DEFAULT_COMPRESSION_LEVEL,
    DEFAULT_WINDOW_LOG,
    open_for_write,
    validate_compression_level,
    validate_window_log,
)


def export_game(
    paths: LutrisPaths,
    slug: str,
    target_dir: Path,
    *,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
    window_log: int = DEFAULT_WINDOW_LOG,
    game_dir_override: Path | None = None,
) -> Path:
    validate_compression_level(compression_level)
    validate_window_log(window_log)

    with connect(paths.db_path) as connection:
        game_row = find_game_by_slug(connection, slug)
    if game_row is None:
        raise GameNotFoundError(slug)

    config_path = paths.games_config_dir / f"{game_row['configpath']}.yml"
    if not config_path.exists():
        raise ConfigNotFoundError(config_path)
    config_text = config_path.read_text(encoding="utf-8")

    game_root = find_game_root(
        paths, config_text, slug, game_row.get("directory"), game_dir_override=game_dir_override
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{slug}.tar.zst"
    partial_path = final_path.with_name(f"{final_path.name}.part")

    try:
        _write_tarball(
            partial_path,
            paths,
            slug,
            game_row,
            config_text,
            game_root,
            compression_level,
            window_log,
        )
    except BaseException:
        partial_path.unlink(missing_ok=True)
        raise

    partial_path.rename(final_path)
    return final_path


def _write_tarball(
    path: Path,
    paths: LutrisPaths,
    slug: str,
    game_row: dict[str, Any],
    config_text: str,
    game_root: Path,
    compression_level: int,
    window_log: int,
) -> None:
    # Strip database 'id' unique key value
    cleaned_game_row = {k: v for k, v in game_row.items() if k != "id"}

    # Check if configpath is post-fixed with installed_at numeric stamp
    installed_at = cleaned_game_row.get("installed_at")
    configpath = cleaned_game_row.get("configpath", "")
    if installed_at and configpath:
        dash_stamp = f"-{str(installed_at)}"
        if configpath.endswith(dash_stamp):
            cleaned_game_row["configpath"] = configpath[: -len(dash_stamp)]

    with open_for_write(path, compression_level, window_log) as compressed_stream:
        with tarfile.open(fileobj=compressed_stream, mode="w|") as tar:
            # Export database content using JSON pretty-print
            _add_json_member(
                tar,
                f"{slug}/database.json",
                strip_paths(cleaned_game_row, slug, GAME_ROOT_PLACEHOLDER, game_root=game_root),
            )

            # Simple text string search/replace handling for config file
            stripped_config = config_text.replace(str(game_root), GAME_ROOT_PLACEHOLDER)
            _add_text_member(tar, f"{slug}/config.yml", stripped_config)

            _add_artwork(tar, paths, slug)
            tar.add(game_root, arcname=f"{slug}/game")


def _add_json_member(tar: tarfile.TarFile, arcname: str, data: Any) -> None:
    content = json.dumps(data, indent=2).encode("utf-8")
    info = tarfile.TarInfo(name=arcname)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def _add_text_member(tar: tarfile.TarFile, arcname: str, text: str) -> None:
    content = text.encode("utf-8")
    info = tarfile.TarInfo(name=arcname)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def _add_artwork(tar: tarfile.TarFile, paths: LutrisPaths, slug: str) -> None:
    for kind in ARTWORK_KINDS:
        source = find_existing_file(
            paths.artwork_dir(kind), kind.stem.format(slug=slug)
        )
        if source:
            tar.add(source, arcname=f"{slug}/{kind.export_name}{source.suffix}")
