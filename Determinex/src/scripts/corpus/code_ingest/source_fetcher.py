"""Source fetcher for corpus intake.

Network fetching is intentionally not implemented here. The safe first path is
local, already-reviewed source directories. External cloning should happen in a
separate approval-controlled step and then enter this fetcher as a local path.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FetchedSource:
    source_path: str
    staged_path: str
    source_hash: str
    provenance_kind: str = "local_path"

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "staged_path": self.staged_path,
            "source_hash": self.source_hash,
            "provenance_kind": self.provenance_kind,
        }


def _tree_hash(path: Path) -> str:
    h = hashlib.blake2b(digest_size=32)
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    for file_path in files:
        rel = file_path.name if path.is_file() else file_path.relative_to(path).as_posix()
        h.update(rel.encode("utf-8", errors="replace"))
        try:
            h.update(file_path.read_bytes())
        except Exception:
            continue
    return h.hexdigest()


def stage_local_source(
    source: Path, staging_root: Path, *, name: str | None = None
) -> FetchedSource:
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    source_hash = _tree_hash(source)
    safe_name = name or f"{source.name}_{source_hash[:12]}"
    dest = staging_root / safe_name
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest)
    else:
        dest.mkdir(parents=True)
        shutil.copy2(source, dest / source.name)
    return FetchedSource(source_path=str(source), staged_path=str(dest), source_hash=source_hash)
