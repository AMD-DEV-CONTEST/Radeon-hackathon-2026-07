from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class UpdateBackup:
    database: str
    metadata: str
    sha256: str
    from_version: str
    to_version: str
    created_at: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_update_backup(
    database: Path,
    backup_dir: Path,
    *,
    from_version: str,
    to_version: str,
    retain: int = 3,
) -> UpdateBackup:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"xenix-{from_version}-to-{to_version}-{stamp}.db"
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    with sqlite3.connect(f"file:{destination.as_posix()}?mode=ro", uri=True) as verification:
        result = verification.execute("PRAGMA integrity_check").fetchone()
    if result != ("ok",):
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Update backup integrity check failed: {result!r}")
    digest = _sha256(destination)
    metadata_path = destination.with_suffix(".json")
    backup = UpdateBackup(
        database=str(destination),
        metadata=str(metadata_path),
        sha256=digest,
        from_version=from_version,
        to_version=to_version,
        created_at=datetime.now(UTC).isoformat(),
    )
    metadata_path.write_text(json.dumps(asdict(backup), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    backups = sorted(backup_dir.glob("xenix-*-to-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for expired in backups[max(retain, 1):]:
        expired.unlink(missing_ok=True)
        expired.with_suffix(".json").unlink(missing_ok=True)
    return backup
