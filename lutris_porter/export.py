import io
import json
import math
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


def filter_config_yaml(config_text: str) -> str:
    exclude_keys = {"game_slug", "name", "script", "service", "service_id", "slug"}
    lines = config_text.splitlines(keepends=True)
    output = []
    skipping = False
    for line in lines:
        if not line.strip():
            if not skipping:
                output.append(line)
            continue
        if line.startswith((" ", "\t")):
            if not skipping:
                output.append(line)
        else:
            parts = line.split(":", 1)
            key = parts[0].strip()
            if key in exclude_keys:
                skipping = True
            else:
                skipping = False
                output.append(line)
    return "".join(output)


def export_game(
    paths: LutrisPaths,
    slug: str,
    target_dir: Path,
    *,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
    window_log: int = DEFAULT_WINDOW_LOG,
    game_dir_override: Path | None = None,
    chunk_size: int | None = None,
) -> Path:
    validate_compression_level(compression_level)
    validate_window_log(window_log)

    # Automatically expand any path that starts with '~'
    target_dir = Path(str(target_dir)).expanduser()
    if game_dir_override is not None:
        game_dir_override = Path(str(game_dir_override)).expanduser()

    with connect(paths.db_path) as connection:
        game_row = find_game_by_slug(connection, slug)
        if not game_row:
            raise GameNotFoundError(slug)

    config_path = paths.games_config_dir / f"{slug}.yml"
    if not config_path.exists():
        raise ConfigNotFoundError(config_path)
    config_text = config_path.read_text(encoding="utf-8")

    # Exclude unwanted top-level keys from config
    config_text = filter_config_yaml(config_text)

    cleaned_game_row = dict(game_row)

    game_root = find_game_root(
        paths,
        config_text,
        slug,
        cleaned_game_row.get("directory"),
        game_dir_override=game_dir_override,
    )

    padding_width = 3
    if chunk_size:
        total_bytes = 0
        if game_root.is_file():
            total_bytes = game_root.stat().st_size
        else:
            for f in game_root.rglob("*"):
                try:
                    if f.is_file() and not f.is_symlink():
                        total_bytes += f.stat().st_size
                except Exception:
                    pass
        total_mb = total_bytes / (1024 * 1024)
        estimated_chunks = math.ceil(total_mb / chunk_size)
        if estimated_chunks < 1:
            estimated_chunks = 1
        padding_width = max(3, len(str(estimated_chunks)))

    target_archive = target_dir / f"{slug}.tar.zst"

    with open_for_write(
        target_archive,
        level=compression_level,
        window_log=window_log,
        chunk_size=chunk_size,
        padding_width=padding_width,
    ) as compressed_stream:
        with tarfile.open(fileobj=compressed_stream, mode="w|") as tar:
            _add_json_member(
                tar,
                f"{slug}/database.json",
                strip_paths(cleaned_game_row, slug, GAME_ROOT_PLACEHOLDER, game_root=game_root),
            )

            stripped_config = config_text.replace(str(game_root), GAME_ROOT_PLACEHOLDER)
            _add_text_member(tar, f"{slug}/config.yml", stripped_config)

            _add_artwork(tar, paths, slug)

            def tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
                prefix = f"{slug}/game"
                if tarinfo.name == prefix:
                    return tarinfo
                if tarinfo.name.startswith(prefix + "/"):
                    rel_path = tarinfo.name[len(prefix) + 1:]
                else:
                    return tarinfo

                # Exclusion Rules
                if rel_path == "config_info" or rel_path.startswith("config_info/"):
                    return None
                if rel_path == "lutris.json" or rel_path.startswith("lutris.json/"):
                    return None
                if rel_path == "shadercache" or rel_path.startswith("shadercache/"):
                    return None
                if rel_path == "gstreamer-1.0" or rel_path.startswith("gstreamer-1.0/"):
                    return None
                if rel_path == "drive_c/proton_shortcuts" or rel_path.startswith("drive_c/proton_shortcuts/"):
                    return None
                if rel_path.startswith("dosdevices/"):
                    sub = rel_path[len("dosdevices/"):]
                    if sub:
                        first_char = sub[0].lower()
                        if "d" <= first_char <= "z":
                            return None
                return tarinfo

            tar.add(game_root, arcname=f"{slug}/game", filter=tar_filter)

    return target_archive


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
    from .paths import ARTWORK_EXTENSIONS
    for kind in ARTWORK_KINDS:
        dest_dir = paths.artwork_dir(kind)
        stem = kind.stem.format(slug=slug)
        found_path = find_existing_file(dest_dir, stem, ARTWORK_EXTENSIONS)
        if found_path and found_path.exists():
            tar.add(found_path, arcname=f"{slug}/{kind.export_name}{found_path.suffix}")
