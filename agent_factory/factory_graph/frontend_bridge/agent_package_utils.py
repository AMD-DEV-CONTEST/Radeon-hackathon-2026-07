from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


def humanize_identifier(value: str) -> str:
    text = re.sub(r"[_\\-]+", " ", str(value or "")).strip()
    return " ".join(part[:1].upper() + part[1:] for part in text.split())


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json_object(path: Path, payload: dict[str, Any]) -> None:
    write_json_objects_atomically({path: payload})


def write_json_objects_atomically(documents: dict[Path, dict[str, Any]]) -> None:
    if not documents:
        return
    originals = {path: path.read_bytes() if path.is_file() else None for path in documents}
    staged: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, payload in documents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                staged[path] = Path(temporary.name)
        for path, temporary_path in staged.items():
            temporary_path.replace(path)
            replaced.append(path)
        staged.clear()
    except Exception:
        for path in reversed(replaced):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
                continue
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".rollback",
                delete=False,
            ) as rollback:
                rollback.write(original)
                rollback.flush()
                os.fsync(rollback.fileno())
                rollback_path = Path(rollback.name)
            rollback_path.replace(path)
        raise
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)


def path_updated_at(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:
        return ""
