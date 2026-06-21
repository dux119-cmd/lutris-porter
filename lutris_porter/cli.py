import argparse
import sys
from pathlib import Path

from .db import connect, list_slugs
from .errors import LutrisPorterError
from .export import export_game
from .importer import import_game
from .paths import LutrisPaths
from .zstd_io import DEFAULT_COMPRESSION_LEVEL, DEFAULT_WINDOW_LOG


def _expand_path(s: str) -> Path:
    return Path(s).expanduser()


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

    export_parser = subparsers.add_parser("export", help="Export a game to a portable tarball")
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
    export_parser.add_argument(
        "--zstd-level",
        type=int,
        default=DEFAULT_COMPRESSION_LEVEL,
        metavar="N",
        help=f"zstd compression level, higher is smaller but slower (default: {DEFAULT_COMPRESSION_LEVEL})",
    )
    export_parser.add_argument(
        "--zstd-window-log",
        type=int,
        default=DEFAULT_WINDOW_LOG,
        metavar="N",
        help=(
            "zstd window size as a power of two, e.g. 27 = 128 MiB; higher "
            f"can compress better on large files but uses more memory (default: {DEFAULT_WINDOW_LOG})"
        ),
    )

    import_parser = subparsers.add_parser("import", help="Import a previously exported game from a tarball")
    import_parser.add_argument(
        "tarball", help="Local path (with ~ support) or http(s):// URL to the <slug>.tar.zst file"
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


def _dispatch(parser: argparse.ArgumentParser, paths: LutrisPaths, args: argparse.Namespace) -> None:
    if args.list_games:
        _print_slugs(paths)
    elif args.command == "export":
        tarball = export_game(
            paths,
            args.slug,
            args.target_dir,
            compression_level=args.zstd_level,
            window_log=args.zstd_window_log,
            game_dir_override=args.game_dir,
        )
        print(f"Exported '{args.slug}' to {tarball}")
    elif args.command == "import":
        slug = import_game(paths, args.tarball, args.target_dir)
        print(f"Imported '{slug}'")
    else:
        parser.print_help()


def _print_slugs(paths: LutrisPaths) -> None:
    with connect(paths.db_path) as connection:
        for slug in list_slugs(connection):
            print(slug)


if __name__ == "__main__":
    sys.exit(main())
