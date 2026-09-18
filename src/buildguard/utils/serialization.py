"""Serialization helpers."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def to_json(value: BaseModel | dict[str, Any]) -> str:
    """Serialize models consistently for logs and JSONL."""
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value, ensure_ascii=False, default=str)


def append_jsonl(path: Path, value: BaseModel | dict[str, Any]) -> None:
    """Append one record, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(to_json(value) + "\n")

