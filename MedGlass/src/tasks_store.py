"""Care-team task assignments.

Maps each follow-up / test / medication item extracted from a note's Plan
section to a staff role. Stored as ``output/tasks.json``:

    {"assignments": {<note_id>: {<item_index>: {"role": "nurse"|"provider",
                                                "assigned_at": iso}}}}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from utils import write_json

LOG = logging.getLogger("medglass.tasks")

TASKS_FILE = Path("output") / "tasks.json"
ROLES = ("nurse", "provider")


def _load() -> dict:
    if not TASKS_FILE.exists():
        return {"assignments": {}}
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        LOG.warning("tasks.json unreadable; starting empty", exc_info=True)
        return {"assignments": {}}
    if isinstance(data, dict) and isinstance(data.get("assignments"), dict):
        return data
    return {"assignments": {}}


def list_tasks() -> dict:
    """Return the full assignments map {note_id: {item_index: {...}}}."""
    return _load().get("assignments", {})


def assign(note_id: str, item: int, role: str | None) -> dict:
    """Set (role in nurse/provider) or clear (role None) an item assignment."""
    data = _load()
    assignments = data.setdefault("assignments", {})
    note_tasks = assignments.setdefault(note_id, {})
    existing = note_tasks.get(str(item), {})
    if role and role in ROLES:
        entry = {
            "role": role,
            "assigned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if existing.get("done"):
            entry["done"] = True
            entry["done_at"] = existing.get("done_at")
        note_tasks[str(item)] = entry
    else:
        note_tasks.pop(str(item), None)
    if not note_tasks:
        assignments.pop(note_id, None)
    write_json(TASKS_FILE, data)
    return assignments


def set_done(note_id: str, item: int, done: bool) -> dict:
    """Mark a next-step item done (keeps its role assignment)."""
    data = _load()
    assignments = data.setdefault("assignments", {})
    note_tasks = assignments.setdefault(note_id, {})
    entry = note_tasks.setdefault(str(item), {})
    if done:
        entry["done"] = True
        entry["done_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        entry.pop("done", None)
        entry.pop("done_at", None)
    if not entry:
        note_tasks.pop(str(item), None)
    if not note_tasks:
        assignments.pop(note_id, None)
    write_json(TASKS_FILE, data)
    return assignments
