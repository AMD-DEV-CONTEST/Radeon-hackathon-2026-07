from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from agent_factory.trace_system.schema import utc_now


class RuntimeLogStore:
    """Append-only log for RuntimeKernel and host/runtime infrastructure issues."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def append(self, *, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "version": "runtime_log.v0",
            "record_id": uuid4().hex,
            "event_type": event_type,
            "created_at": utc_now(),
            "payload": payload,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str))
                handle.write("\n")
