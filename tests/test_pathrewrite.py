from lutris_porter.pathrewrite import (
    map_strings,
    restore_game_root,
    restore_paths,
    strip_game_root,
    strip_paths,
)

PLACEHOLDER = "{{LUTRIS_GAME_ROOT}}"


def test_strip_game_root_replaces_up_to_and_including_slug():
    path = "/home/user/Games/my-slug/bin/run.sh"
    assert strip_game_root(path, "my-slug", PLACEHOLDER) == f"{PLACEHOLDER}/bin/run.sh"


def test_strip_game_root_leaves_path_unchanged_without_slug_segment():
    path = "/usr/bin/wine"
    assert strip_game_root(path, "my-slug", PLACEHOLDER) == path


def test_strip_game_root_leaves_relative_paths_unchanged():
    assert strip_game_root("relative/path", "my-slug", PLACEHOLDER) == "relative/path"


def test_strip_game_root_handles_bare_slug_directory():
    path = "/home/user/Games/my-slug"
    assert strip_game_root(path, "my-slug", PLACEHOLDER) == PLACEHOLDER


def test_restore_game_root_round_trips():
    stripped = f"{PLACEHOLDER}/bin/run.sh"
    restored = restore_game_root(stripped, PLACEHOLDER, "/new/location/my-slug")
    assert restored == "/new/location/my-slug/bin/run.sh"


def test_restore_game_root_leaves_paths_without_placeholder_unchanged():
    path = "/usr/bin/wine"
    assert restore_game_root(path, PLACEHOLDER, "/new/location") == path


def test_map_strings_recurses_through_nested_structures():
    data = {"game": {"exe": "/a/my-slug/x"}, "tags": ["/a/my-slug/y", 5, None]}
    result = map_strings(data, lambda value: value.upper())
    assert result == {"game": {"exe": "/A/MY-SLUG/X"}, "tags": ["/A/MY-SLUG/Y", 5, None]}


def test_strip_paths_then_restore_paths_round_trips_a_full_structure():
    original = {
        "game": {"exe": "/home/user/Games/my-slug/bin/run.sh", "prefix": "/home/user/Games/my-slug/prefix"},
        "unrelated": "/usr/bin/wine",
        "name": "My Game",
        "count": 3,
    }

    stripped = strip_paths(original, "my-slug", PLACEHOLDER)
    assert stripped["game"]["exe"] == f"{PLACEHOLDER}/bin/run.sh"
    assert stripped["unrelated"] == "/usr/bin/wine"

    restored = restore_paths(stripped, "/new/Games/my-slug", PLACEHOLDER)
    assert restored == {
        "game": {
            "exe": "/new/Games/my-slug/bin/run.sh",
            "prefix": "/new/Games/my-slug/prefix",
        },
        "unrelated": "/usr/bin/wine",
        "name": "My Game",
        "count": 3,
    }
