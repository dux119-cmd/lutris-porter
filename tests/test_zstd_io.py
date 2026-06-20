from pathlib import Path

import pytest

from lutris_porter.errors import InvalidCompressionSettingError
from lutris_porter.zstd_io import (
    open_for_read,
    open_for_write,
    validate_compression_level,
    validate_window_log,
)


def test_validate_compression_level_accepts_default():
    assert validate_compression_level(12) == 12


def test_validate_compression_level_rejects_out_of_bounds():
    with pytest.raises(InvalidCompressionSettingError):
        validate_compression_level(999)


def test_validate_window_log_accepts_default():
    assert validate_window_log(27) == 27


def test_validate_window_log_accepts_zero_as_auto():
    assert validate_window_log(0) == 0


def test_validate_window_log_rejects_out_of_bounds():
    with pytest.raises(InvalidCompressionSettingError):
        validate_window_log(5)  # below the documented [10, 31] range


def test_write_then_read_round_trips_with_custom_settings(tmp_path: Path):
    path = tmp_path / "test.tar.zst"
    payload = b"some test content " * 1000

    with open_for_write(path, level=19, window_log=27) as f:
        f.write(payload)

    with open_for_read(path) as f:
        assert f.read() == payload


def test_write_then_read_round_trips_with_max_window_log(tmp_path: Path):
    """open_for_read must be able to handle whatever window_log open_for_write used,
    even at the upper bound, without the caller doing anything extra."""
    path = tmp_path / "test.tar.zst"
    payload = b"x" * 10_000

    with open_for_write(path, level=3, window_log=31) as f:
        f.write(payload)

    with open_for_read(path) as f:
        assert f.read() == payload
