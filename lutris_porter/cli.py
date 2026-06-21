import argparse
import sys
from pathlib import Path

from .db import connect, list_slugs
from .errors import LutrisPorterError
from .export import export_game
from .importer import import_game
from .paths import LutrisPaths
from .zstd_io import DEFAULT_COMPRESSION_LEVEL, DEFAULT_WINDOW_LOG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lutris-porter",
        description="Export and import Lutris games as portable tarballs",
    )
    parser.add_argument(
        "-l", "--list-games", action="store_true", help="List installed game slugs and exit"
    )

    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser("export", help="Export a game to a tarball")
    export_parser.add_argument("slug", help="Slug of the game to export")
    export_parser.add_argument(
        "target_dir", type=Path, help="Directory to write <slug>.tar.zst into"
    )
    export_parser.add_argument(
        "--game-dir",
        type=Path,
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
        help=f"zstd window log (default: {DEFAULT_WINDOW_LOG})",
    )
    export_parser.add_argument(
        "--chunk-size",
        type=int,
        metavar="MB",
        help="Chunk size in MB to split the exported archive",
    )

    import_parser = subparsers.add_parser("import", help="Import a game from a tarball or chunk list")
    import_parser.add_argument(
        "tarball", type=str, help="Path or URL to the exported archive or chunk list file/URL"
    )
    import_parser.add_argument("target_dir", type=Path, help="Directory to install the game into")

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
            chunk_size=args.chunk_size,
        )
        print(f"Exported '{args.slug}' to {tarball}")
    elif args.command == "import":
        slug = import_game(paths, args.tarball, args.target_dir)
        print(f"Imported '{slug}'")
    else:
        parser.print_help()


def _print_slugs(paths: LutrisPaths) -> None:
    with connect(paths.db_path) as connection:
        slugs = list_slugs(connection)
        for slug in slugs:
            print(slug)


if __name__ == "__main__":
    sys.exit(main())
