from __future__ import annotations

from difflib import SequenceMatcher
import os
from pathlib import Path
import shutil
import stat
from tempfile import NamedTemporaryFile


def text_change_summary(before: str, after: str) -> dict[str, int]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    added_lines = 0
    removed_lines = 0
    matcher = SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for operation, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if operation in {"replace", "delete"}:
            removed_lines += before_end - before_start
        if operation in {"replace", "insert"}:
            added_lines += after_end - after_start
    return {
        "before_bytes": len(before.encode("utf-8")),
        "after_bytes": len(after.encode("utf-8")),
        "before_lines": len(before_lines),
        "after_lines": len(after_lines),
        "added_lines": added_lines,
        "removed_lines": removed_lines,
    }


def atomic_write_bytes(target: Path, content: bytes) -> None:
    original_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile("wb", delete=False, dir=str(target.parent)) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if original_mode is not None:
            temp_path.chmod(original_mode)
        temp_path.replace(target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def atomic_write_file(target: Path, source: Path) -> None:
    original_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    temp_path: Path | None = None
    try:
        with source.open("rb") as source_handle:
            with NamedTemporaryFile("wb", delete=False, dir=str(target.parent)) as target_handle:
                temp_path = Path(target_handle.name)
                shutil.copyfileobj(source_handle, target_handle)
                target_handle.flush()
                os.fsync(target_handle.fileno())
        if original_mode is not None:
            temp_path.chmod(original_mode)
        temp_path.replace(target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
