import unittest
from pathlib import Path

from lutris_porter.pathrewrite import (
    map_strings,
    restore_game_root,
    restore_paths,
    strip_game_root,
    strip_paths,
)

PLACEHOLDER = "{{LUTRIS_GAME_ROOT}}"


class MapStringsTests(unittest.TestCase):
    def test_transforms_string_leaf(self) -> None:
        self.assertEqual(map_strings("abc", str.upper), "ABC")

    def test_transforms_strings_inside_nested_dicts_and_lists(self) -> None:
        data = {"a": "x", "b": ["y", {"c": "z"}]}
        result = map_strings(data, str.upper)
        self.assertEqual(result, {"a": "X", "b": ["Y", {"c": "Z"}]})

    def test_leaves_non_string_leaves_untouched(self) -> None:
        data = {"count": 3, "ratio": 1.5, "enabled": True, "missing": None}
        self.assertEqual(map_strings(data, str.upper), data)

    def test_does_not_mutate_the_original(self) -> None:
        original = {"a": ["x"]}
        map_strings(original, str.upper)
        self.assertEqual(original, {"a": ["x"]})


class StripGameRootTests(unittest.TestCase):
    def test_replaces_segment_up_to_and_including_slug(self) -> None:
        path = "/home/user/Games/hades/save.dat"
        result = strip_game_root(path, "hades", PLACEHOLDER)
        self.assertEqual(result, f"{PLACEHOLDER}/save.dat")

    def test_returns_just_placeholder_when_slug_is_final_segment(self) -> None:
        result = strip_game_root("/home/user/Games/hades", "hades", PLACEHOLDER)
        self.assertEqual(result, PLACEHOLDER)

    def test_leaves_relative_paths_untouched(self) -> None:
        self.assertEqual(strip_game_root("hades/save.dat", "hades", PLACEHOLDER), "hades/save.dat")

    def test_leaves_paths_without_the_slug_untouched(self) -> None:
        path = "/home/user/Games/other/save.dat"
        self.assertEqual(strip_game_root(path, "hades", PLACEHOLDER), path)

    def test_does_not_match_slug_as_a_substring_of_a_segment(self) -> None:
        path = "/home/user/Games/hades2/save.dat"
        self.assertEqual(strip_game_root(path, "hades", PLACEHOLDER), path)

    def test_game_root_takes_precedence_over_slug_segment_matching(self) -> None:
        game_root = Path("/mnt/data/install/hades")
        path = f"{game_root}/save.dat"
        result = strip_game_root(path, "hades", PLACEHOLDER, game_root=game_root)
        self.assertEqual(result, f"{PLACEHOLDER}/save.dat")

    def test_game_root_exact_match_returns_just_placeholder(self) -> None:
        game_root = Path("/mnt/data/install/hades")
        result = strip_game_root(str(game_root), "hades", PLACEHOLDER, game_root=game_root)
        self.assertEqual(result, PLACEHOLDER)

    def test_falls_back_to_slug_matching_when_path_is_outside_game_root(self) -> None:
        game_root = Path("/mnt/data/install/hades")
        path = "/home/user/Games/hades/save.dat"
        result = strip_game_root(path, "hades", PLACEHOLDER, game_root=game_root)
        self.assertEqual(result, f"{PLACEHOLDER}/save.dat")


class RestoreGameRootTests(unittest.TestCase):
    def test_replaces_placeholder_with_new_root(self) -> None:
        result = restore_game_root(f"{PLACEHOLDER}/save.dat", PLACEHOLDER, "/new/root")
        self.assertEqual(result, "/new/root/save.dat")

    def test_leaves_strings_without_placeholder_untouched(self) -> None:
        self.assertEqual(
            restore_game_root("/unrelated/path", PLACEHOLDER, "/new/root"), "/unrelated/path"
        )


class StripAndRestorePathsRoundTripTests(unittest.TestCase):
    def test_round_trip_through_the_same_root_restores_original_paths(self) -> None:
        original = {
            "exe": "/home/user/Games/hades/hades.exe",
            "files": ["/home/user/Games/hades/save.dat", "/etc/unrelated"],
            "count": 3,
        }
        stripped = strip_paths(original, "hades", PLACEHOLDER)
        restored = restore_paths(stripped, "/home/user/Games/hades", PLACEHOLDER)
        self.assertEqual(restored, original)

    def test_round_trip_through_a_different_root_relocates_paths(self) -> None:
        original = {"exe": "/home/user/Games/hades/hades.exe"}
        stripped = strip_paths(original, "hades", PLACEHOLDER)
        restored = restore_paths(stripped, "/new/install/hades", PLACEHOLDER)
        self.assertEqual(restored, {"exe": "/new/install/hades/hades.exe"})

    def test_strip_paths_replaces_slug_segment_everywhere_in_tree(self) -> None:
        original = {"exe": "/home/user/Games/hades/hades.exe"}
        stripped = strip_paths(original, "hades", PLACEHOLDER)
        self.assertEqual(stripped, {"exe": f"{PLACEHOLDER}/hades.exe"})


if __name__ == "__main__":
    unittest.main()
