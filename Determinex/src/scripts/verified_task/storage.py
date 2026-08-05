"""Storage inventory and compression for T-backed verified task runs."""

from __future__ import annotations

import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import default_verified_root, ensure_on_staging_root


@dataclass(slots=True)
class StorageEntry:
    path: str
    size_bytes: int
    mtime: float
    kind: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def inventory(root: Path | None = None, *, min_age_seconds: int = 0) -> list[StorageEntry]:
    root = (root or default_verified_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ensure_on_staging_root(root)
    cutoff = time.time() - min_age_seconds
    entries: list[StorageEntry] = []
    for item in sorted(root.iterdir()):
        try:
            stat = item.stat()
        except OSError:
            continue
        if stat.st_mtime > cutoff:
            continue
        size = directory_size(item) if item.is_dir() else stat.st_size
        entries.append(
            StorageEntry(
                path=str(item),
                size_bytes=size,
                mtime=stat.st_mtime,
                kind="dir" if item.is_dir() else "file",
            )
        )
    return entries


def compress_directory(path: Path, *, delete_original: bool = False) -> Path:
    path = ensure_on_staging_root(path)
    if not path.is_dir():
        raise ValueError(f"expected directory to compress: {path}")
    archive = path.with_suffix(path.suffix + ".zip")
    ensure_on_staging_root(archive.parent)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in path.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(path.parent))
    if delete_original:
        import shutil

        shutil.rmtree(path)
    return archive
