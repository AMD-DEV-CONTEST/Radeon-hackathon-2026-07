"""Append-only local audit trail for agent actions (enterprise accountability)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class AuditTrail:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **payload: Any) -> None:
        row = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 20) -> str:
        if not self.path.exists():
            return "(audit trail empty)"
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        return "\n".join(lines) if lines else "(audit trail empty)"
