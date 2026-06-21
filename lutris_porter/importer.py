"""Reverses export_game by streaming a zstd-compressed tarball straight to
its destination. database.json and config.yml are read first (the importer
relies on export_game writing them before the game/ directory), then the
game/ directory's members are extracted directly into the final install
location member-by-member - no intermediate full copy.
"""

import json
import os
import shutil
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .db import connect, insert_game
from .errors import DestinationExistsError, LutrisPorterError, InstalledSlugAlreadyExistsError
from .paths import ARTWORK_EXTENSIONS, ARTWORK_KINDS, GAME_ROOT_PLACEHOLDER, LutrisPaths
from .pathrewrite import restore_paths
from .zstd_io import open_for_read

COPY_CHUNK_SIZE = 1024 * 1024
GAME_MEMBER_PREFIX = "game"


def import_game(paths: LutrisPaths, tarball_path: str | Path, target_dir: Path) -> str:
    target_dir = Path(str(target_dir)).expanduser()
    with open_for_read(tarball_path) as decompressed_stream:
        with tarfile.open(fileobj=decompressed_stream, mode="r|") as tar:
            return _import_members(paths, tar, target_dir)


def _import_members(paths: LutrisPaths, tar: tarfile.TarFile, target_dir: Path) -> str:
    slug: str | None = None
    database: dict[str, Any] | None = None
    config_text: str | None = None
    install_root: Path | None = None
    existing_id: int | None = None

    for member in tar:
        member_path = _strip_top_level(member.name)
        if member_path is None:
            continue  # the bare top-level slug/ entry, if present

        if member_path in ("database.json", "database.yml"):
            database = json.loads(_read_member(tar, member).decode("utf-8"))
            slug, install_root, existing_id = _resolve_install_root(paths, database, target_dir)
            continue

        if slug is None or install_root is None:
            raise LutrisPorterError("Malformed export: database.json must be the first entry")

        if member_path == "config.yml":
            config_text = _read_member(tar, member).decode("utf-8")
        elif _is_game_member(member_path):
            _extract_game_member(tar, member, member_path, install_root)
        else:
            _install_artwork_member(tar, member, member_path, paths, slug)

    if database is None or slug is None or install_root is None:
        raise LutrisPorterError("Malformed export: no database.json found")

    restored_database = restore_paths(database, str(install_root), GAME_ROOT_PLACEHOLDER)
    
    if config_text is not None:
        restored_config = config_text.replace(GAME_ROOT_PLACEHOLDER, str(install_root))
    else:
        restored_config = ""

    config_file_path = paths.games_config_dir / f"{restored_database['configpath']}.yml"
    config_file_path.parent.mkdir(parents=True, exist_ok=True)
    config_file_path.write_text(restored_config, encoding="utf-8")

    with connect(paths.db_path) as connection:
        insert_game(connection, _prepare_for_insert(restored_database, existing_id))

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
) -> tuple[str, Path, int | None]:
    slug = database["slug"]
    existing_id = None
    with connect(paths.db_path) as connection:
        row = connection.execute("SELECT id, installed FROM games WHERE slug = ?", (slug,)).fetchone()
        if row:
            if row["installed"] == 0:
                existing_id = row["id"]
            else:
                raise InstalledSlugAlreadyExistsError(slug)

    install_root = target_dir / slug
    if install_root.exists():
        raise DestinationExistsError(install_root)
    return slug, install_root, existing_id


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


def _prepare_for_insert(database: dict[str, Any], existing_id: int | None) -> dict[str, Any]:
    """Clobber/overwrite fields with the exported content per-usual.
    If existing_id is provided, reuse it. Otherwise, let SQLite assign a fresh one.
    """
    res = {
        **database,
        "lastplayed": None,
        "playtime": 0,
        "installed_at": int(time.time()),
    }
    if existing_id is not None:
        res["id"] = existing_id
    elif "id" in res:
        del res["id"]
    return res
