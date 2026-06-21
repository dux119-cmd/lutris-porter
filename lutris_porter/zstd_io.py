"""Wraps compression.zstd with the specific settings lutris-porter uses.

Defaults favor compression ratio over speed - level 5 with a 2 GiB
long-distance-matching window - since a game is archived once and read
rarely, the opposite tradeoff from something like a build cache. Both are
adjustable via the CLI.

Reading always raises the decompressor's window_log_max to its maximum,
so the importer can open any window size our own exporter might have been
told to use, regardless of which level/window-log the export used.
"""

import os
from compression import zstd
from pathlib import Path
from typing import IO

from .errors import InvalidCompressionSettingError

DEFAULT_COMPRESSION_LEVEL = 5
DEFAULT_WINDOW_LOG = 31


def validate_compression_level(level: int) -> int:
    lower, upper = zstd.CompressionParameter.compression_level.bounds()
    if not lower <= level <= upper:
        raise InvalidCompressionSettingError("compression level", level, lower, upper)
    return level


def validate_window_log(window_log: int) -> int:
    lower, upper = zstd.CompressionParameter.window_log.bounds()
    if window_log != 0 and not lower <= window_log <= upper:
        raise InvalidCompressionSettingError(
            "window log", window_log, lower, upper, zero_means_auto=True
        )
    return window_log


def open_for_write(path: Path, level: int, window_log: int) -> IO[bytes]:
    options = {
        zstd.CompressionParameter.checksum_flag: True,
        zstd.CompressionParameter.compression_level: level,
        zstd.CompressionParameter.window_log: window_log,
        zstd.CompressionParameter.strategy: zstd.Strategy.lazy2,
        zstd.CompressionParameter.nb_workers: os.cpu_count() + 1,
        zstd.CompressionParameter.enable_long_distance_matching: True,
    }
    return zstd.ZstdFile(path, "wb", options=options)


def open_for_read(source: Path | IO[bytes]) -> IO[bytes]:
    """Accept a local Path or any readable file-like object (e.g. HTTP response)."""
    _, max_window_log = zstd.DecompressionParameter.window_log_max.bounds()
    options = {zstd.DecompressionParameter.window_log_max: max_window_log}
    return zstd.ZstdFile(source, "rb", options=options)
