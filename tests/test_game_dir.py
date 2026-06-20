from pathlib import Path

import pytest

from lutris_porter.errors import GameDirectoryNotFoundError
from lutris_porter.game_dir import find_game_root, read_default_game_path
from lutris_porter.paths import LutrisPaths
from lutris_porter.yaml_io import write_yaml


def _paths_with_system_yml(tmp_path: Path, game_path: str | None) -> LutrisPaths:
    paths = LutrisPaths.for_home(tmp_path)
    if game_path is not None:
        write_yaml(paths.system_yml_path, {"system": {"game_path": game_path}})
    return paths


def test_finds_root_from_absolute_exe_path_when_slug_present(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, None)
    config = {"game": {"exe": "/home/user/Games/my-slug/bin/run.sh"}}
    assert str(find_game_root(paths, config, "my-slug", None)) == "/home/user/Games/my-slug"


def test_falls_back_to_directory_column_when_slug_missing_from_absolute_exe(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, None)
    config = {"game": {"exe": "/opt/renamed-folder/run.sh"}}
    fallback = "/home/user/Games/my-slug"
    assert str(find_game_root(paths, config, "my-slug", fallback)) == fallback


def test_falls_back_to_directory_column_when_no_exe_present(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, None)
    fallback = "/home/user/Games/my-slug"
    assert str(find_game_root(paths, {}, "my-slug", fallback)) == fallback


def test_relative_exe_resolves_via_default_game_path(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, "/nvme1/games")
    config = {"game": {"exe": "drive_c/Game/run.exe"}}
    assert str(find_game_root(paths, config, "my-slug", None)) == "/nvme1/games/my-slug"


def test_directory_column_takes_priority_over_relative_exe_fallback(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, "/nvme1/games")
    config = {"game": {"exe": "drive_c/Game/run.exe"}}
    explicit_directory = "/some/other/explicit/my-slug"
    assert str(find_game_root(paths, config, "my-slug", explicit_directory)) == explicit_directory


def test_raises_when_relative_exe_present_but_system_yml_missing(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, None)
    config = {"game": {"exe": "drive_c/Game/run.exe"}}
    with pytest.raises(GameDirectoryNotFoundError):
        find_game_root(paths, config, "my-slug", None)


def test_raises_when_no_source_available(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, None)
    with pytest.raises(GameDirectoryNotFoundError):
        find_game_root(paths, {"game": {}}, "my-slug", None)


def test_read_default_game_path_returns_none_when_system_yml_missing(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, None)
    assert read_default_game_path(paths) is None


def test_read_default_game_path_reads_game_path(tmp_path: Path):
    paths = _paths_with_system_yml(tmp_path, "/nvme1/games")
    assert read_default_game_path(paths) == "/nvme1/games"
