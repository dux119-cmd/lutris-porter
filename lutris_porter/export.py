"""Streams a game's files, database row, config, and artwork straight into
a zstd-compressed tarball. Nothing is staged or copied to a temporary
location first - source files are read once and written once, which
matters when a game install is tens of gigabytes.

Member order inside the tarball is deliberate: database.yml first, then
config.yml and artwork, then the (potentially huge) game/ directory last.
The importer relies on this order to extract game/ directly to its final
destination in a single streaming pass.
"""

import io
import tarfile
from pathlib import Path
from typing import Any

from .db import connect, find_game_by_slug
from .errors import ConfigNotFoundError, GameNotFoundError
from .game_dir import find_game_root
from .paths import ARTWORK_KINDS, GAME_ROOT_PLACEHOLDER, LutrisPaths, find_existing_file
from .pathrewrite import strip_paths
from .yaml_io import dump_yaml_bytes, load_yaml
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
    config = load_yaml(config_path)

    game_root = find_game_root(paths, config, slug, game_row.get("directory"))

    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{slug}.tar.zst"
    partial_path = final_path.with_name(f"{final_path.name}.part")

    try:
        _write_tarball(
            partial_path, paths, slug, game_row, config, game_root, compression_level, window_log
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
    config: dict[str, Any],
    game_root: Path,
    compression_level: int,
    window_log: int,
) -> None:
    with open_for_write(path, compression_level, window_log) as compressed_stream:
        with tarfile.open(fileobj=compressed_stream, mode="w|") as tar:
            _add_yaml_member(tar, f"{slug}/database.yml", strip_paths(game_row, slug, GAME_ROOT_PLACEHOLDER))
            _add_yaml_member(tar, f"{slug}/config.yml", strip_paths(config, slug, GAME_ROOT_PLACEHOLDER))
            _add_artwork(tar, paths, slug)
            tar.add(game_root, arcname=f"{slug}/game")


def _add_yaml_member(tar: tarfile.TarFile, arcname: str, data: Any) -> None:
    content = dump_yaml_bytes(data)
    info = tarfile.TarInfo(name=arcname)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def _add_artwork(tar: tarfile.TarFile, paths: LutrisPaths, slug: str) -> None:
    for kind in ARTWORK_KINDS:
        source = find_existing_file(paths.artwork_dir(kind), kind.stem.format(slug=slug))
        if source:
            tar.add(source, arcname=f"{slug}/{kind.export_name}{source.suffix}")
