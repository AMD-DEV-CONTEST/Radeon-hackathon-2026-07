"""Atomic file writes: temp file in the same directory, then `os.replace`
onto the target, so a reader either sees the old contents or the new
contents, never a half-written file. Mirrors the pattern already used
locally in `core/utils/upload_handler.py::_atomic_write_json` -- extracted
here because every other caller (`bg_jobs.py`, `settings.py`,
`preset_manager.py`, `integrations.py`, `cookbook_serve_lifecycle.py`,
`builtin_actions.py`, `core/memory/skills.py`) imports `from core.atomic_io
import atomic_write_json` / `atomic_write_text`, but this module never
actually existed in this checkout.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Union

PathLike = Union[str, "os.PathLike[str]"]


def _atomic_write_bytes(path: PathLike, data: bytes) -> None:
    path = str(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".atomic-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                shutil.copy2(path, path + ".bak")
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: PathLike, data: Any, indent: int = 2) -> None:
    """Serialize `data` as JSON and write it to `path` atomically."""
    _atomic_write_bytes(path, json.dumps(data, indent=indent, ensure_ascii=False).encode("utf-8"))


def atomic_write_text(path: PathLike, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` atomically."""
    _atomic_write_bytes(path, text.encode(encoding))


def atomic_read_json(path: PathLike, default: Any = None) -> Any:
    """Read+parse JSON from `path`, returning `default` if the file is
    missing or corrupt (a crash mid-write should never take down the
    caller -- the `.bak` sibling written by `atomic_write_json` is the
    manual recovery path, not an automatic one, since callers differ on
    whether a corrupt primary should fall back to `.bak` or to `default`).
    """
    p = Path(path)
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
