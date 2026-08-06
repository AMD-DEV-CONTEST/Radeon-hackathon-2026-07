from __future__ import annotations

import os
from pathlib import Path


def load_agentfactory_dotenv(path: Path | None = None) -> Path | None:
    dotenv_path = path or _find_dotenv(Path.cwd())
    if dotenv_path is None or not dotenv_path.exists():
        return None

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_quotes(value.strip()))
    return dotenv_path


def _find_dotenv(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
    return None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
