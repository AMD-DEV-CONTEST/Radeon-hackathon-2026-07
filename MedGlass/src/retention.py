"""Retention / data-destruction policy.

Deletes archived notes older than ``retention_days`` along with their photos
and care-team task assignments, satisfying a configurable PHI retention window.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("medglass.retention")

NOTES_DIR = Path("output") / "notes"
PHOTOS_DIR = Path("output") / "photos"
TASKS_FILE = Path("output") / "tasks.json"


def _created_ts(value) -> float:
    """created_at may be an ISO string or a float epoch; parse both."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))\
            .astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _delete_path(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        LOG.warning("retention: failed to remove %s: %s", path, exc)


def purge_old(retention_days: int) -> dict:
    """Remove notes + photos + task entries older than retention_days.

    Returns a summary dict. Raises on invalid input. Missing stores are treated
    as already clean.
    """
    cutoff = time.time() - retention_days * 86400
    result = {"notes": 0, "photos": 0, "tasks": 0, "skipped": 0}

    if not NOTES_DIR.exists():
        return result
    for path in sorted(NOTES_DIR.glob("mg_*.json")):
        try:
            text = path.read_text(encoding="utf-8")
            from crypto import decrypt_text, is_encrypted
            if is_encrypted(text):
                text = decrypt_text(text)
            record = json.loads(text)
        except Exception as exc:
            LOG.warning("retention: skipping unreadable %s: %s", path.name, exc)
            result["skipped"] += 1
            continue
        created = _created_ts(record.get("created_at"))
        if created and created < cutoff:
            _delete_path(path)
            result["notes"] += 1
            for photo in record.get("photos") or []:
                name = (photo.get("original") or "").rsplit("/", 1)[-1]
                if name:
                    _delete_path(PHOTOS_DIR / name)
                    result["photos"] += 1

    if TASKS_FILE.exists():
        try:
            tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            tasks = {}
        if isinstance(tasks, dict):
            removed = 0
            for note_id in list(tasks.keys()):
                if note_id.startswith("mg_") and (NOTES_DIR / f"{note_id}.json").exists() is False:
                    del tasks[note_id]
                    removed += 1
            result["tasks"] = removed
            if removed:
                try:
                    from utils import write_json
                    write_json(TASKS_FILE, tasks)
                except Exception as exc:
                    LOG.warning("retention: failed to prune tasks: %s", exc)

    LOG.info("retention purge complete: %s", result)
    return result
