"""Thread-safe JSONL and atomic summary writer."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Self

import orjson
from pydantic import BaseModel, SecretStr

SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
}
REDACTED = "********"


def redact(value: Any) -> Any:
    """Recursively redact common credential fields and Pydantic secrets."""
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, BaseModel):
        return redact(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            str(key): REDACTED if str(key).lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class JsonlWriter:
    """Append records without interleaving writes across threads."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._stream = self.path.open("ab")

    def write(self, record: BaseModel | dict[str, Any]) -> None:
        payload = orjson.dumps(redact(record), option=orjson.OPT_UTC_Z) + b"\n"
        with self._lock:
            self._stream.write(payload)

    def flush(self) -> None:
        with self._lock:
            self._stream.flush()
            os.fsync(self._stream.fileno())

    def close(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.flush()
                self._stream.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def atomic_write_json(path: Path, data: BaseModel | dict[str, Any]) -> None:
    """Replace a JSON summary only after the complete temporary file is durable."""
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = orjson.dumps(redact(data), option=orjson.OPT_INDENT_2 | orjson.OPT_UTC_Z)
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
