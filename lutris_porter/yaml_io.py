"""Thin YAML helpers so the rest of the codebase doesn't import yaml directly."""

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False)


def load_yaml_bytes(data: bytes) -> Any:
    return yaml.safe_load(data) or {}


def dump_yaml_bytes(data: Any) -> bytes:
    return yaml.safe_dump(data, sort_keys=False).encode("utf-8")
