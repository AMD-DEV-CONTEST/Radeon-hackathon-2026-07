"""Private JSONL-backed multi-turn memory stored entirely on local disk."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .security import PermissionPolicy


class LocalMemoryStore:
    """Append-only session memory with recursive metadata redaction."""

    def __init__(
        self,
        path: str | Path,
        policy: PermissionPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.policy = policy or PermissionPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._clock_source = "injected_clock" if clock is not None else "system_utc"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        else:
            os.chmod(self.path, 0o600)

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.policy.require("write_memory")
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValueError("unsupported memory role")
        if not content.strip():
            raise ValueError("memory content must not be empty")
        record = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata": self.policy.redact_payload(dict(metadata or {})),
            "timestamp_utc": self._clock().astimezone(timezone.utc).isoformat(),
            "timestamp_source": self._clock_source,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def recent(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        self.policy.require("read_memory")
        if limit <= 0:
            return []
        records: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("session_id") == session_id:
                    records.append(record)
        return records[-limit:]

    def clear_session(self, session_id: str) -> int:
        """Delete one local session and return the number of removed turns.

        The rewrite is atomic: records are written to a temporary sibling file
        which is then renamed over the original, so a crash mid-write cannot
        corrupt the session store.
        """
        self.policy.require("write_memory")
        all_records: list[dict[str, Any]] = []
        removed = 0
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("session_id") == session_id:
                    removed += 1
                else:
                    all_records.append(record)
        if removed == 0:
            return 0
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for record in all_records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
        os.chmod(self.path, 0o600)
        return removed
