#!/usr/bin/env python3.14

"""lutris-porter: export and import Lutris games as portable zstd tarballs.

Single-file rewrite of the lutris_porter package. Compression settings are
fixed (level 5, 2 GiB long-distance-matching window) and no longer exposed
as CLI flags -- one tool, one good default.

Tarball layout (export writes members in this order; import depends on it):
    <slug>/database.json   -- the games-table row, paths made portable
    <slug>/config.yml      -- the Lutris config, paths made portable
    <slug>/<artwork>       -- banner/coverart/logo, if present
    <slug>/game/...        -- the game's install directory, streamed last

Requires Python 3.14+ for `compression.zstd`.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from compression import zstd
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any


class LutrisPorterError(Exception):
    """Raised for all expected failures; the CLI prints these and exits 1."""


# --------------------------------------------------------------------------
# Lutris on-disk layout
# --------------------------------------------------------------------------

GAME_ROOT_PLACEHOLDER = "{{LUTRIS_GAME_ROOT}}"
ARTWORK_EXTENSIONS = ("png", "jpg")


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


def artwork_paths(paths: LutrisPaths, slug: str) -> dict[str, Path]:
    """Map each tarball artwork name to its on-disk path stem (no extension).

    There are exactly three artwork files, each named after the slug; the
    actual file is whichever of stem.png / stem.jpg exists.
    """
    return {
        "banner": paths.banners_dir / slug,
        "coverart": paths.coverart_dir / slug,
        "logo": paths.icons_dir / f"lutris_{slug}",
    }


# --------------------------------------------------------------------------
# pga.db access -- plain dicts via sqlite3.Row, no ORM
# --------------------------------------------------------------------------


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def list_slugs(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute("SELECT slug FROM games ORDER BY slug").fetchall()
    return [row["slug"] for row in rows]


def find_game_by_slug(
    connection: sqlite3.Connection, slug: str
) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM games WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def insert_game(connection: sqlite3.Connection, game: dict[str, Any]) -> int:
    columns = ", ".join(game.keys())
    placeholders = ", ".join("?" for _ in game)
    cursor = connection.execute(
        f"INSERT OR REPLACE INTO games ({columns}) VALUES ({placeholders})",
        tuple(game.values()),
    )
    connection.commit()
    return cursor.lastrowid


# --------------------------------------------------------------------------
# Path portability -- swap the game's real install path for a placeholder
# --------------------------------------------------------------------------


def map_strings(value: Any, transform: Callable[[str], str]) -> Any:
    """Recursively rebuild value, applying transform to every string leaf."""
    if isinstance(value, dict):
        return {key: map_strings(item, transform) for key, item in value.items()}
    if isinstance(value, list):
        return [map_strings(item, transform) for item in value]
    if isinstance(value, str):
        return transform(value)
    return value


def strip_game_root(path: str, game_root: Path) -> str:
    root = str(game_root)
    if not path.startswith(root):
        return path
    remainder = path[len(root) :].lstrip("/")
    return (
        f"{GAME_ROOT_PLACEHOLDER}/{remainder}" if remainder else GAME_ROOT_PLACEHOLDER
    )


def restore_game_root(path: str, new_root: str) -> str:
    return (
        path.replace(GAME_ROOT_PLACEHOLDER, new_root)
        if GAME_ROOT_PLACEHOLDER in path
        else path
    )


def strip_paths(data: Any, game_root: Path) -> Any:
    return map_strings(data, lambda value: strip_game_root(value, game_root))


def restore_paths(data: Any, new_root: str) -> Any:
    return map_strings(data, lambda value: restore_game_root(value, new_root))


# --------------------------------------------------------------------------
# Locating a game's install directory
# --------------------------------------------------------------------------
# Tried in order, most explicit first:
#   1. an explicit --game-dir override
#   2. config.yml's game.exe, if absolute and containing the slug as a
#      path segment -- everything up to and including that segment
#   3. the database's `directory` column, if present
#   4. config.yml's game.exe, if relative -- Lutris installed under its
#      default games directory (system.yml's system.game_path) / slug


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
    raise LutrisPorterError(
        f"Could not derive the game's directory from the slug '{slug}' or YML records.\n\n"
        "Use the '--game-dir /path/to/game' export flag instead."
    )


def _exe_path(config_text: str) -> str | None:
    for line in config_text.splitlines():
        if "exe:" in line:
            _, _, value = line.partition("exe:")
            value = value.strip().strip("'\"")
            if value:
                return value
    return None


def _root_from_absolute_exe(config_text: str, slug: str) -> str | None:
    exe = _exe_path(config_text)
    if not exe or not exe.startswith("/"):
        return None
    segments = exe.split("/")
    if slug not in segments:
        return None
    return "/".join(segments[: segments.index(slug) + 1])


def _root_from_default_game_path(
    paths: LutrisPaths, config_text: str, slug: str
) -> str | None:
    exe = _exe_path(config_text)
    if not exe or exe.startswith("/"):
        return None
    default_game_path = _read_default_game_path(paths)
    if not default_game_path:
        return None
    return f"{default_game_path.rstrip('/')}/{slug}"


def _read_default_game_path(paths: LutrisPaths) -> str | None:
    if not paths.system_yml_path.exists():
        return None
    for line in paths.system_yml_path.read_text(encoding="utf-8").splitlines():
        if "game_path:" in line:
            _, _, value = line.partition("game_path:")
            value = value.strip().strip("'\"")
            if value:
                return value
    return None


# --------------------------------------------------------------------------
# zstd compression -- fixed settings, no CLI knobs
# --------------------------------------------------------------------------
# Level 5 with a 2 GiB long-distance-matching window favors compression
# ratio over speed, since a game is archived once and read rarely.

_COMPRESSION_LEVEL = 5
_WINDOW_LOG = 31


def _open_for_write(path: Path) -> IO[bytes]:
    options = {
        zstd.CompressionParameter.checksum_flag: True,
        zstd.CompressionParameter.compression_level: _COMPRESSION_LEVEL,
        zstd.CompressionParameter.window_log: _WINDOW_LOG,
        zstd.CompressionParameter.strategy: zstd.Strategy.lazy2,
        zstd.CompressionParameter.nb_workers: os.cpu_count() + 1,
        zstd.CompressionParameter.enable_long_distance_matching: True,
    }
    return zstd.ZstdFile(path, "wb", options=options)


def _open_for_read(source: Path | IO[bytes]) -> IO[bytes]:
    """Accept a local Path or any readable file-like object (e.g. HTTP response)."""
    _, max_window_log = zstd.DecompressionParameter.window_log_max.bounds()
    options = {zstd.DecompressionParameter.window_log_max: max_window_log}
    return zstd.ZstdFile(source, "rb", options=options)


# --------------------------------------------------------------------------
# Export -- stream db row, config, artwork, and game files into a tarball
# --------------------------------------------------------------------------
# Nothing is staged to a temp location first; source files are read once
# and written once, which matters when a game install is tens of GB.

EXCLUDED_DATABASE_KEYS = frozenset(
    {
        "id",
        "sortname",
        "installer_slug",
        "parent_slug",
        "executable",
        "lastplayed",
        "playtime",
        "installed_at",
        "has_custom_banner",
        "has_custom_icon",
        "has_custom_coverart_big",
        "service",
        "service_id",
        "discord_id",
    }
)
EXCLUDED_CONFIG_KEYS = frozenset(
    {
        "game_slug",
        "name",
        "script",
        "service",
        "service_id",
        "slug",
    }
)
EXCLUDED_GAME_PATHS = frozenset(
    {
        "config_info",
        "lutris.json",
        "system.reg.old",
        "shadercache",
        "gstreamer-1.0",
        "drive_c/proton_shortcuts",
    }
)
_DOSDEVICES_DIR = "dosdevices"


def strip_config_keys(text: str) -> str:
    """Remove specified top-level YAML keys and their indented child lines."""
    result: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip()
        if stripped and not stripped[0].isspace():
            key = stripped.split(":", 1)[0]
            skipping = key in EXCLUDED_CONFIG_KEYS
        if not skipping:
            result.append(line)
    return "".join(result)


def _make_game_filter(slug: str) -> Callable[[tarfile.TarInfo], tarfile.TarInfo | None]:
    prefix = f"{slug}/game/"

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if not info.name.startswith(prefix):
            return info
        relative = info.name[len(prefix) :]
        for excluded in EXCLUDED_GAME_PATHS:
            if relative == excluded or relative.startswith(f"{excluded}/"):
                return None
        parts = relative.split("/", 2)
        if (
            len(parts) >= 2
            and parts[0] == _DOSDEVICES_DIR
            and parts[1]
            and "d" <= parts[1][0] <= "z"
        ):
            return None
        return info

    return _filter


def export_game(
    paths: LutrisPaths,
    slug: str,
    target_dir: Path,
    *,
    game_dir_override: Path | None = None,
) -> Path:
    with connect(paths.db_path) as connection:
        game_row = find_game_by_slug(connection, slug)
    if game_row is None:
        raise LutrisPorterError(f"No game found with slug '{slug}'")

    config_path = paths.games_config_dir / f"{game_row['configpath']}.yml"
    if not config_path.exists():
        raise LutrisPorterError(f"Config file not found: {config_path}")
    config_text = config_path.read_text(encoding="utf-8")

    # Strip the installed_at numeric suffix from configpath, if present.
    installed_at = game_row.get("installed_at")
    configpath = game_row.get("configpath", "")
    if installed_at and configpath:
        dash_stamp = f"-{installed_at}"
        if configpath.endswith(dash_stamp):
            game_row["configpath"] = configpath[: -len(dash_stamp)]

    # Strip remaining useless values from the database
    for key in EXCLUDED_DATABASE_KEYS:
        game_row.pop(key, None)

    game_root = find_game_root(
        paths,
        config_text,
        slug,
        game_row.get("directory"),
        game_dir_override=game_dir_override,
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / f"{slug}.tar.zst"
    partial_path = final_path.with_name(f"{final_path.name}.part")

    try:
        _write_tarball(partial_path, paths, slug, game_row, config_text, game_root)
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
) -> None:
    with _open_for_write(path) as compressed_stream:
        with tarfile.open(fileobj=compressed_stream, mode="w|") as tar:
            _add_bytes_member(
                tar,
                f"{slug}/database.json",
                json.dumps(strip_paths(game_row, game_root), indent=2).encode("utf-8"),
            )

            stripped_config = strip_config_keys(
                config_text.replace(str(game_root), GAME_ROOT_PLACEHOLDER)
            )
            _add_bytes_member(
                tar, f"{slug}/config.yml", stripped_config.encode("utf-8")
            )

            _add_artwork(tar, paths, slug)
            tar.add(game_root, arcname=f"{slug}/game", filter=_make_game_filter(slug))


def _add_bytes_member(tar: tarfile.TarFile, arcname: str, content: bytes) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def _add_artwork(tar: tarfile.TarFile, paths: LutrisPaths, slug: str) -> None:
    for export_name, stem in artwork_paths(paths, slug).items():
        source = next(
            (p for ext in ARTWORK_EXTENSIONS if (p := Path(f"{stem}.{ext}")).exists()),
            None,
        )
        if source:
            tar.add(source, arcname=f"{slug}/{export_name}{source.suffix}")


# --------------------------------------------------------------------------
# Import -- reverse of export_game, streamed straight to the destination
# --------------------------------------------------------------------------
# database.json and config.yml are read first (export_game guarantees
# this order); game/ members are then extracted directly to their final
# location, member-by-member, with no intermediate full copy.

_COPY_CHUNK_SIZE = 1024 * 1024
_GAME_MEMBER_PREFIX = "game"


@contextmanager
def _open_source(tarball: Path | str) -> Iterator[IO[bytes]]:
    """Yield a readable byte stream for a local path or HTTP(S) URL."""
    if isinstance(tarball, str) and tarball.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(tarball) as response:
                yield response
        except urllib.error.URLError as exc:
            raise LutrisPorterError(
                f"Failed to fetch tarball from {tarball!r}: {exc.reason}"
            ) from exc
    else:
        path = (
            Path(tarball).expanduser()
            if isinstance(tarball, str)
            else tarball.expanduser()
        )
        with open(path, "rb") as f:
            yield f


def import_game(paths: LutrisPaths, tarball: Path | str, target_dir: Path) -> str:
    with _open_source(tarball) as raw:
        with _open_for_read(raw) as decompressed_stream:
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

        if member_path == "database.json":
            database = json.loads(_read_member(tar, member).decode("utf-8"))
            slug, install_root, existing_id = _resolve_install_root(
                paths, database, target_dir
            )
            continue

        if slug is None or install_root is None:
            raise LutrisPorterError(
                "Malformed export: database.json must be the first entry"
            )

        if member_path == "config.yml":
            config_text = _read_member(tar, member).decode("utf-8")
        elif _is_game_member(member_path):
            _extract_game_member(tar, member, member_path, install_root)
        else:
            _install_artwork_member(tar, member, member_path, paths, slug)

    if database is None or slug is None or install_root is None:
        raise LutrisPorterError("Malformed export: no database.json found")

    restored_database = restore_paths(database, str(install_root))
    restored_config = (
        config_text.replace(GAME_ROOT_PLACEHOLDER, str(install_root))
        if config_text
        else ""
    )

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
    return member_path == _GAME_MEMBER_PREFIX or member_path.startswith(
        f"{_GAME_MEMBER_PREFIX}/"
    )


def _read_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    return tar.extractfile(member).read()


def _resolve_install_root(
    paths: LutrisPaths, database: dict[str, Any], target_dir: Path
) -> tuple[str, Path, int | None]:
    slug = database["slug"]
    existing_id = None
    with connect(paths.db_path) as connection:
        row = connection.execute(
            "SELECT id, installed FROM games WHERE slug = ?", (slug,)
        ).fetchone()
        if row:
            if row["installed"] == 0:
                existing_id = row["id"]
            else:
                raise LutrisPorterError(
                    f"A game with slug '{slug}' is already installed in the database"
                )

    install_root = target_dir / slug
    if install_root.exists():
        raise LutrisPorterError(f"Destination already exists: {install_root}")
    return slug, install_root, existing_id


def _extract_game_member(
    tar: tarfile.TarFile, member: tarfile.TarInfo, member_path: str, install_root: Path
) -> None:
    relative = PurePosixPath(member_path).relative_to(_GAME_MEMBER_PREFIX)
    destination = install_root if str(relative) == "." else install_root / relative

    if member.isdir():
        destination.mkdir(parents=True, exist_ok=True)
        return

    destination.parent.mkdir(parents=True, exist_ok=True)

    if member.issym():
        os.symlink(member.linkname, destination)
        return

    if not member.isfile():
        return  # skip device/fifo/socket members

    with destination.open("wb") as out_file:
        shutil.copyfileobj(tar.extractfile(member), out_file, _COPY_CHUNK_SIZE)
    os.chmod(destination, member.mode)


def _install_artwork_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    member_path: str,
    paths: LutrisPaths,
    slug: str,
) -> None:
    name, _, extension = member_path.rpartition(".")
    if extension not in ARTWORK_EXTENSIONS:
        return
    stem = artwork_paths(paths, slug).get(name)
    if stem is None:
        return

    destination = Path(f"{stem}.{extension}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as out_file:
        shutil.copyfileobj(tar.extractfile(member), out_file)


def _prepare_for_insert(
    database: dict[str, Any], existing_id: int | None
) -> dict[str, Any]:
    """Reset play stats and timestamps; reuse the existing DB id if any."""
    result = {
        **database,
        "installed_at": int(time.time()),
    }
    if existing_id is not None:
        result["id"] = existing_id
    elif "id" in result:
        del result["id"]
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _expand_path(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lutris-porter",
        description="Export and import Lutris games as portable tarballs",
    )
    parser.add_argument(
        "-l",
        "--list",
        dest="list_games",
        action="store_true",
        help="List installed game slugs and exit",
    )

    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser(
        "export", help="Export a game to a portable tarball"
    )
    export_parser.add_argument("slug", help="Slug of the game to export")
    export_parser.add_argument(
        "target_dir", type=_expand_path, help="Directory to write <slug>.tar.zst into"
    )
    export_parser.add_argument(
        "--game-dir",
        type=_expand_path,
        metavar="DIR",
        help="Explicitly specify the game's installation directory (overrides automatic discovery)",
    )

    import_parser = subparsers.add_parser(
        "import", help="Import a previously exported game from a tarball"
    )
    import_parser.add_argument(
        "tarball",
        help="Local path (with ~ support) or http(s):// URL to the <slug>.tar.zst file",
    )
    import_parser.add_argument(
        "target_dir", type=_expand_path, help="Directory to install the game into"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = LutrisPaths.for_home(Path.home())

    try:
        _dispatch(parser, paths, args)
    except LutrisPorterError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def _dispatch(
    parser: argparse.ArgumentParser, paths: LutrisPaths, args: argparse.Namespace
) -> None:
    if args.list_games:
        with connect(paths.db_path) as connection:
            for slug in list_slugs(connection):
                print(slug)
    elif args.command == "export":
        tarball = export_game(
            paths, args.slug, args.target_dir, game_dir_override=args.game_dir
        )
        print(f"Exported '{args.slug}' to {tarball}")
    elif args.command == "import":
        slug = import_game(paths, args.tarball, args.target_dir)
        print(f"Imported '{slug}'")
    else:
        parser.print_help()


if __name__ == "__main__":
    sys.exit(main())
