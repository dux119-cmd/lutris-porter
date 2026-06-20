import sqlite3
import time
from pathlib import Path

from lutris_porter.db import connect, find_game_by_slug
from lutris_porter.export import export_game
from lutris_porter.importer import import_game
from lutris_porter.paths import LutrisPaths
from lutris_porter.yaml_io import load_yaml, write_yaml

GAMES_TABLE_SCHEMA = """
CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, sortname TEXT, slug TEXT,
installer_slug TEXT, parent_slug TEXT, platform TEXT, runner TEXT, executable TEXT,
directory TEXT, updated DATETIME, lastplayed INTEGER, installed INTEGER,
installed_at INTEGER, year INTEGER, configpath TEXT, has_custom_banner INTEGER,
has_custom_icon INTEGER, has_custom_coverart_big INTEGER, playtime REAL,
service TEXT, service_id TEXT, discord_id TEXT)
"""


def _make_lutris_home(home: Path) -> LutrisPaths:
    paths = LutrisPaths.for_home(home)
    for directory in (paths.games_config_dir, paths.banners_dir, paths.coverart_dir, paths.icons_dir):
        directory.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(paths.db_path) as connection:
        connection.execute(GAMES_TABLE_SCHEMA)
        connection.commit()

    return paths


def _install_fake_game_with_absolute_exe(paths: LutrisPaths, install_dir: Path, slug: str, configpath: str) -> None:
    game_root = install_dir / slug
    (game_root / "bin").mkdir(parents=True)
    (game_root / "bin" / "run.sh").write_text("#!/bin/sh\necho run\n")

    with connect(paths.db_path) as connection:
        connection.execute(
            "INSERT INTO games (id, name, slug, installer_slug, platform, runner, executable, "
            "directory, configpath, installed, installed_at, lastplayed, playtime) "
            "VALUES (1, 'My Game', ?, ?, 'linux', 'wine', ?, ?, ?, 1, 1700000000, 1700050000, 1.5)",
            (slug, slug, str(game_root / "bin" / "run.sh"), str(game_root), configpath),
        )
        connection.commit()

    write_yaml(
        paths.games_config_dir / f"{configpath}.yml",
        {"game": {"exe": str(game_root / "bin" / "run.sh"), "working_dir": str(game_root)}},
    )

    paths.banners_dir.joinpath(f"{slug}.png").write_bytes(b"banner")


def _install_fake_game_with_relative_exe(
    paths: LutrisPaths, default_game_path: Path, slug: str, configpath: str
) -> None:
    """Simulates a game installed via Lutris's global default games directory:
    relative exe in config.yml, no `directory` set in the database."""
    game_root = default_game_path / slug
    (game_root / "drive_c").mkdir(parents=True)
    (game_root / "drive_c" / "run.exe").write_text("pretend exe\n")

    write_yaml(paths.system_yml_path, {"system": {"game_path": str(default_game_path)}})

    with connect(paths.db_path) as connection:
        connection.execute(
            "INSERT INTO games (id, name, slug, installer_slug, platform, runner, configpath, "
            "installed, installed_at, lastplayed, playtime) "
            "VALUES (1, 'My Game', ?, ?, 'linux', 'wine', ?, 1, 1700000000, 1700050000, 1.5)",
            (slug, slug, configpath),
        )
        connection.commit()

    write_yaml(
        paths.games_config_dir / f"{configpath}.yml",
        {"game": {"exe": "drive_c/run.exe"}},
    )


def test_export_then_import_round_trip(tmp_path: Path):
    slug = "my-slug"
    configpath = "my-slug-1700000000"

    source_home = tmp_path / "source_home"
    source_install_dir = tmp_path / "source_games"
    source_paths = _make_lutris_home(source_home)
    _install_fake_game_with_absolute_exe(source_paths, source_install_dir, slug, configpath)

    tarball_dir = tmp_path / "export_out"
    tarball_dir.mkdir()
    tarball = export_game(source_paths, slug, tarball_dir)
    assert tarball.name == f"{slug}.tar.zst"

    dest_home = tmp_path / "dest_home"
    dest_install_dir = tmp_path / "dest_games"
    dest_paths = _make_lutris_home(dest_home)

    before_import = int(time.time())
    imported_slug = import_game(dest_paths, tarball, dest_install_dir)
    assert imported_slug == slug

    with connect(dest_paths.db_path) as connection:
        row = find_game_by_slug(connection, slug)
    new_root = dest_install_dir / slug
    assert row["executable"] == str(new_root / "bin" / "run.sh")
    assert row["directory"] == str(new_root)
    assert row["configpath"] == configpath

    # play stats are reset, install stamp reflects the import, not the original install
    assert row["lastplayed"] is None
    assert row["playtime"] == 0
    assert row["installed_at"] >= before_import
    assert row["installed_at"] != 1700000000

    config = load_yaml(dest_paths.games_config_dir / f"{configpath}.yml")
    assert config["game"]["exe"] == str(new_root / "bin" / "run.sh")
    assert config["game"]["working_dir"] == str(new_root)

    assert (new_root / "bin" / "run.sh").read_text() == "#!/bin/sh\necho run\n"
    assert dest_paths.banners_dir.joinpath(f"{slug}.png").read_bytes() == b"banner"


def test_export_with_relative_exe_uses_default_game_path(tmp_path: Path):
    slug = "default-path-game"
    configpath = "default-path-game-1700000000"

    source_home = tmp_path / "source_home"
    default_game_path = tmp_path / "nvme1" / "games"
    source_paths = _make_lutris_home(source_home)
    _install_fake_game_with_relative_exe(source_paths, default_game_path, slug, configpath)

    tarball_dir = tmp_path / "export_out"
    tarball_dir.mkdir()
    tarball = export_game(source_paths, slug, tarball_dir)

    dest_home = tmp_path / "dest_home"
    dest_install_dir = tmp_path / "dest_games"
    dest_paths = _make_lutris_home(dest_home)

    import_game(dest_paths, tarball, dest_install_dir)

    new_root = dest_install_dir / slug
    assert (new_root / "drive_c" / "run.exe").read_text() == "pretend exe\n"

    # the relative exe itself is untouched - Lutris resolves it against
    # its own system.yml on the new machine
    config = load_yaml(dest_paths.games_config_dir / f"{configpath}.yml")
    assert config["game"]["exe"] == "drive_c/run.exe"
