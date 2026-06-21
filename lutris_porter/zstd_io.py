import io
import os
import re
import urllib.request
import urllib.parse
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


class ChunkedFileWriter(io.RawIOBase):
    def __init__(self, base_path: Path, chunk_size_mb: int, padding_width: int):
        self.base_path = base_path
        self.chunk_size_bytes = chunk_size_mb * 1024 * 1024
        self.padding_width = padding_width
        self.current_chunk_idx = 1
        self.current_chunk_bytes_written = 0
        self.total_bytes_written = 0
        self.current_file = None
        self._open_next_chunk()

    def _open_next_chunk(self):
        if self.current_file:
            self.current_file.close()
        chunk_ext = f"{self.current_chunk_idx:0{self.padding_width}d}"
        chunk_path = self.base_path.with_name(f"{self.base_path.name}.{chunk_ext}")
        self.current_file = open(chunk_path, "wb")
        self.current_chunk_idx += 1
        self.current_chunk_bytes_written = 0

    def write(self, b):
        view = memoryview(b)
        total_written = 0
        while total_written < len(view):
            remaining_in_chunk = self.chunk_size_bytes - self.current_chunk_bytes_written
            if remaining_in_chunk <= 0:
                self._open_next_chunk()
                remaining_in_chunk = self.chunk_size_bytes

            to_write = min(len(view) - total_written, remaining_in_chunk)
            self.current_file.write(view[total_written:total_written + to_write])
            self.current_chunk_bytes_written += to_write
            total_written += to_write
            self.total_bytes_written += to_write
        return total_written

    def flush(self):
        if self.current_file:
            self.current_file.flush()

    def close(self):
        if self.current_file:
            self.current_file.close()
            self.current_file = None

    def tell(self):
        return self.total_bytes_written

    def writable(self):
        return True


def open_for_write(
    path: Path, level: int, window_log: int, chunk_size: int | None = None, padding_width: int = 3
) -> IO[bytes]:
    options = {
        zstd.CompressionParameter.checksum_flag: True,
        zstd.CompressionParameter.compression_level: level,
        zstd.CompressionParameter.window_log: window_log,
        zstd.CompressionParameter.strategy: zstd.Strategy.lazy2,
        zstd.CompressionParameter.nb_workers: os.cpu_count() + 1,
        zstd.CompressionParameter.enable_long_distance_matching: True,
    }
    if chunk_size:
        fileobj = ChunkedFileWriter(path, chunk_size, padding_width)
        return zstd.ZstdFile(fileobj, "wb", options=options)
    return zstd.ZstdFile(path, "wb", options=options)


class MultiStreamReader(io.RawIOBase):
    def __init__(self, sources_iter, first_chunk_data=b""):
        self.sources_iter = sources_iter
        self.first_chunk_data = first_chunk_data
        self.current_stream = None
        self.exhausted = False

    def _get_next_stream(self):
        if self.current_stream:
            self.current_stream.close()
            self.current_stream = None

        try:
            next_src = next(self.sources_iter)
            self.current_stream = open_source(next_src)
        except StopIteration:
            self.exhausted = True
        except Exception:
            self.exhausted = True

    def read(self, n=-1):
        if n is None:
            n = -1

        res = b""
        if self.first_chunk_data:
            if n < 0:
                res += self.first_chunk_data
                self.first_chunk_data = b""
            else:
                chunk = self.first_chunk_data[:n]
                res += chunk
                self.first_chunk_data = self.first_chunk_data[len(chunk):]
                if len(res) == n:
                    return res

        while not self.exhausted and (n < 0 or len(res) < n):
            if self.current_stream is None:
                self._get_next_stream()
                if self.exhausted:
                    break

            to_read = -1 if n < 0 else (n - len(res))
            data = self.current_stream.read(to_read)
            if not data:
                self._get_next_stream()
            else:
                res += data

        return res

    def readable(self):
        return True

    def close(self):
        if self.current_stream:
            self.current_stream.close()
            self.current_stream = None
        self.exhausted = True


def open_source(src: str | Path):
    src_str = str(src).strip()
    if src_str.startswith(("http://", "https://")):
        req = urllib.request.Request(
            src_str, headers={"User-Agent": "Mozilla/5.0 (lutris-porter)"}
        )
        return urllib.request.urlopen(req)
    else:
        return open(Path(src_str), "rb")


def get_chunk_info(src_str: str) -> tuple[str, int, int] | None:
    match = re.search(r"\.(\d+)$", src_str)
    if match:
        digits = match.group(1)
        width = len(digits)
        start_val = int(digits)
        base_url = src_str[:-width]
        return base_url, start_val, width
    return None


def parse_chunk_list(src: str | Path, content: str) -> list[str]:
    lines = []
    src_str = str(src).strip()
    is_url = src_str.startswith(("http://", "https://"))

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("http://", "https://")) or os.path.isabs(line):
            lines.append(line)
        else:
            if is_url:
                lines.append(urllib.parse.urljoin(src_str, line))
            else:
                parent = Path(src_str).parent
                lines.append(str(parent / line))
    return lines


def make_stream_reader(initial_src: str | Path) -> io.RawIOBase:
    f = open_source(initial_src)
    magic = f.read(4)

    # Detect if it's a valid zstd binary signature
    if magic == b"\x28\xb5\x2f\xfd":
        src_str = str(initial_src).strip()
        chunk_info = get_chunk_info(src_str)
        if chunk_info:
            base_url, start_val, width = chunk_info
            def chunk_gen():
                curr = start_val + 1
                while True:
                    yield f"{base_url}{curr:0{width}d}"
                    curr += 1

            reader = MultiStreamReader(chunk_gen(), first_chunk_data=magic)
            reader.current_stream = f
            return reader
        else:
            def single_gen():
                if False:
                    yield
            reader = MultiStreamReader(single_gen(), first_chunk_data=magic)
            reader.current_stream = f
            return reader
    else:
        # Fallback to loading it as an explicit line-by-line file list configuration
        rest = f.read()
        f.close()
        content = (magic + rest).decode("utf-8", errors="ignore")
        lines = parse_chunk_list(initial_src, content)
        reader = MultiStreamReader(iter(lines))
        return reader


def open_for_read(path: str | Path) -> IO[bytes]:
    _, max_window_log = zstd.DecompressionParameter.window_log.bounds()
    options = {zstd.DecompressionParameter.window_log_max: max_window_log}
    reader = make_stream_reader(path)
    return zstd.ZstdFile(reader, "rb", options=options)
