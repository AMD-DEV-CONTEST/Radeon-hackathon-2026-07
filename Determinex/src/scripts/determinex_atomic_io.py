"""scripts/determinex_atomic_io.py — canonical atomic file-write helpers.

write_text_atomic()/write_json_atomic() were independently copy-pasted, near
byte-for-byte identical, into at least pb_pool_status.py and
pb_missing_intake.py (both: write to a temp file, `Path.replace()` into
place, retry up to 10x with a 0.25s sleep on PermissionError -- Windows
Defender or another process can briefly hold a lock on a just-written file).
One canonical, tenacity-backed implementation instead of N hand-rolled
copies that could silently drift out of sync with each other.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed


@retry(
    retry=retry_if_exception_type(PermissionError),
    stop=stop_after_attempt(10),
    wait=wait_fixed(0.25),
    reraise=True,
)
def _replace_with_retry(tmp: Path, path: Path) -> None:
    tmp.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` atomically (temp file + rename), retrying past
    transient Windows PermissionErrors on the final rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as f:
        f.write(text)
        tmp = Path(f.name)
    _replace_with_retry(tmp, path)


def write_json_atomic(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, indent=2) + "\n")


class _EmptyRead(Exception):
    """Internal signal only -- file read as empty (writer mid-rename), retry
    like a decode error rather than treating it as final."""


def load_json_with_retry(path: Path, default: Any) -> Any:
    """Read+parse JSON, retrying past a torn read of a file another process
    is concurrently rewriting with write_json_atomic() above. An empty read
    or a JSONDecodeError both retry up to 5x/0.2s; if it's still empty after
    that, return `default` silently (never seen real content -- not an
    error), but a genuine decode error that never resolves DOES propagate."""
    if not path.is_file():
        return default

    @retry(
        retry=retry_if_exception_type((json.JSONDecodeError, _EmptyRead)),
        stop=stop_after_attempt(5),
        wait=wait_fixed(0.2),
        reraise=True,
    )
    def _attempt() -> Any:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            raise _EmptyRead()
        return json.loads(text)

    try:
        return _attempt()
    except _EmptyRead:
        return default
