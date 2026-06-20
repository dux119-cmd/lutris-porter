"""Reverses export_game by streaming a zstd-compressed tarball straight to
its destination. database.yml and config.yml are read first (the importer
relies on export_game writing them before the game/ directory), then the
game/ directory's members are extracted directly into the final install
location member-by-member - no intermediate full copy.
"""

import os
import shutil
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .db import connect, insert_game, slug_exists
from .errors import DestinationExistsError, LutrisPorterError, SlugAlreadyExistsError
from .paths import ARTWORK_EXTENSIONS, ARTWORK_KINDS, GAME_ROOT_PLACEHOLDER, LutrisPaths
from .pathrewrite import restore_paths
from .yaml_io import load_yaml_bytes, write_yaml
from .zstd_io import open_for_read

COPY_CHUNK_SIZE = 1024 * 1024
GAME_MEMBER_PREFIX = "game"


def import_game(paths: LutrisPaths, tarball_path: Path, target_dir: Path) -> str:
    with open_for_read(tarball_path) as decompressed_stream:
        with tarfile.open(fileobj=decompressed_stream, mode="r|") as tar:
            return _import_members(paths, tar, target_dir)


def _import_members(paths: LutrisPaths, tar: tarfile.TarFile, target_dir: Path) -> str:
    slug: str | None = None
    database: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    install_root: Path | None = None

    for member in tar:
        member_path = _strip_top_level(member.name)
        if member_path is None:
            continue  # the bare top-level slug/ entry, if present

        if member_path == "database.yml":
            database = load_yaml_bytes(_read_member(tar, member))
            slug, install_root = _resolve_install_root(paths, database, target_dir)
            continue

        if slug is None or install_root is None:
            raise LutrisPorterError("Malformed export: database.yml must be the first entry")

        if member_path == "config.yml":
            config = load_yaml_bytes(_read_member(tar, member))
        elif _is_game_member(member_path):
            _extract_game_member(tar, member, member_path, install_root)
        else:
            _install_artwork_member(tar, member, member_path, paths, slug)

    if database is None or slug is None or install_root is None:
        raise LutrisPorterError("Malformed export: no database.yml found")

    restored_database = restore_paths(database, str(install_root), GAME_ROOT_PLACEHOLDER)
    restored_config = restore_paths(config or {}, str(install_root), GAME_ROOT_PLACEHOLDER)

    write_yaml(paths.games_config_dir / f"{database['configpath']}.yml", restored_config)
    with connect(paths.db_path) as connection:
        insert_game(connection, _prepare_for_insert(restored_database))

    return slug


def _strip_top_level(name: str) -> str | None:
    _, _, rest = name.partition("/")
    return rest or None


def _is_game_member(member_path: str) -> bool:
    return member_path == GAME_MEMBER_PREFIX or member_path.startswith(f"{GAME_MEMBER_PREFIX}/")


def _read_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    return tar.extractfile(member).read()


def _resolve_install_root(
    paths: LutrisPaths, database: dict[str, Any], target_dir: Path
) -> tuple[str, Path]:
    slug = database["slug"]
    with connect(paths.db_path) as connection:
        if slug_exists(connection, slug):
            raise SlugAlreadyExistsError(slug)

    install_root = target_dir / slug
    if install_root.exists():
        raise DestinationExistsError(install_root)
    return slug, install_root


def _extract_game_member(
    tar: tarfile.TarFile, member: tarfile.TarInfo, member_path: str, install_root: Path
) -> None:
    relative = PurePosixPath(member_path).relative_to(GAME_MEMBER_PREFIX)
    destination = install_root if str(relative) == "." else install_root / relative

    if member.isdir():
        destination.mkdir(parents=True, exist_ok=True)
        return

    destination.parent.mkdir(parents=True, exist_ok=True)

    if member.issym():
        os.symlink(member.linkname, destination)
        return

    if not member.isfile():
        return  # skip device/fifo/socket members - irrelevant to game directories

    with destination.open("wb") as out_file:
        shutil.copyfileobj(tar.extractfile(member), out_file, COPY_CHUNK_SIZE)
    os.chmod(destination, member.mode)


def _install_artwork_member(
    tar: tarfile.TarFile, member: tarfile.TarInfo, member_path: str, paths: LutrisPaths, slug: str
) -> None:
    for kind in ARTWORK_KINDS:
        for extension in ARTWORK_EXTENSIONS:
            if member_path != f"{kind.export_name}.{extension}":
                continue
            dest_dir = paths.artwork_dir(kind)
            dest_dir.mkdir(parents=True, exist_ok=True)
            destination = dest_dir / f"{kind.stem.format(slug=slug)}.{extension}"
            with destination.open("wb") as out_file:
                shutil.copyfileobj(tar.extractfile(member), out_file)
            return


def _prepare_for_insert(database: dict[str, Any]) -> dict[str, Any]:
    """Drop the original row id so sqlite assigns a fresh one, and reset
    play stats so the import is recorded as a fresh install happening now.
    """
    without_id = {key: value for key, value in database.items() if key != "id"}
    return {
        **without_id,
        "lastplayed": None,
        "playtime": 0,
        "installed_at": int(time.time()),
    }
