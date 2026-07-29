from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from src.privacy.guard import redact_text


class SessionMemory:
    """Lightweight local memory for private agent sessions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {"notes": [], "facts": [], "history": []}
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
                self._data.setdefault("notes", [])
                self._data.setdefault("facts", [])
                self._data.setdefault("history", [])
        except (json.JSONDecodeError, OSError, TypeError):
            # Corrupt memory must not crash demos — quarantine and start clean.
            bak = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(bak)
            except OSError:
                pass
            self._data = {"notes": [], "facts": [], "history": []}

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def add_note(self, note: str) -> str:
        safe, _ = redact_text(note)
        item = {"ts": datetime.now().isoformat(timespec="seconds"), "note": safe}
        with self._lock:
            self._data.setdefault("notes", []).append(item)
        self.save()
        return f"Saved note ({len(self._data['notes'])} total)."

    def add_fact(self, fact: str) -> str:
        safe, _ = redact_text(fact)
        item = {"ts": datetime.now().isoformat(timespec="seconds"), "fact": safe}
        with self._lock:
            self._data.setdefault("facts", []).append(item)
        self.save()
        return f"Saved fact ({len(self._data['facts'])} total)."

    def recall(self, limit: int = 8) -> str:
        notes = self._data.get("notes", [])[-limit:]
        facts = self._data.get("facts", [])[-limit:]
        lines = ["## Facts"]
        lines += [f"- {x['fact']}" for x in facts] or ["- (none)"]
        lines.append("## Notes")
        lines += [f"- {x['note']}" for x in notes] or ["- (none)"]
        return "\n".join(lines)

    def append_history(self, role: str, content: str) -> None:
        safe, _ = redact_text(content)
        with self._lock:
            self._data.setdefault("history", []).append(
                {"ts": datetime.now().isoformat(timespec="seconds"), "role": role, "content": safe}
            )
            self._data["history"] = self._data["history"][-100:]
        self.save()

    def recent_turns(self, limit: int = 8) -> list[dict[str, str]]:
        rows = self._data.get("history", [])[-limit:]
        return [{"role": str(x.get("role", "")), "content": str(x.get("content", ""))} for x in rows]

    def format_dialogue(self, limit: int = 8) -> str:
        turns = self.recent_turns(limit)
        if not turns:
            return "(no prior dialogue)"
        lines: list[str] = []
        for t in turns:
            role = "User" if t["role"] == "user" else "Assistant"
            lines.append(f"{role}: {t['content']}")
        return "\n".join(lines)
