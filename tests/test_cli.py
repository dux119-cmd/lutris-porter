from pathlib import Path

from lutris_porter.cli import build_parser


def test_export_defaults_to_documented_compression_settings():
    parser = build_parser()
    args = parser.parse_args(["export", "my-slug", "/tmp/out"])
    assert args.zstd_level == 12
    assert args.zstd_window_log == 27


def test_export_accepts_custom_compression_flags():
    parser = build_parser()
    args = parser.parse_args(
        ["export", "my-slug", "/tmp/out", "--zstd-level", "19", "--zstd-window-log", "30"]
    )
    assert args.zstd_level == 19
    assert args.zstd_window_log == 30


def test_invalid_compression_level_is_rejected_before_any_work(tmp_path: Path, capsys):
    from lutris_porter.cli import main
    from lutris_porter.paths import LutrisPaths

    # use an isolated, nonexistent HOME so this can't touch a real Lutris install
    import os

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    os.environ["HOME"] = str(fake_home)

    paths = LutrisPaths.for_home(fake_home)
    paths.games_config_dir.mkdir(parents=True)

    exit_code = main(["export", "does-not-exist", str(tmp_path / "out"), "--zstd-level", "999"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Invalid compression level" in captured.err
