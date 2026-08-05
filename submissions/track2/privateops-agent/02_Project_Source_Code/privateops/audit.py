from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from privateops.models import AgentResponse


class AuditTrail:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "audit_trail.jsonl"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def append(self, prompt: str, response: AgentResponse) -> dict[str, Any]:
        entry = {
            "audit_id": f"audit-{uuid.uuid4().hex[:12]}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "answer_preview": response.answer[:240],
            "permission_level": response.permission.level,
            "permission_reason": response.permission.reason,
            "evidence_sources": [item.source for item in response.evidence],
            "memory_updates": dict(response.memory_updates),
            "provider": response.provider,
            "plan": [item.to_dict() for item in response.plan],
            "tool_results": [item.to_dict() for item in response.tool_results],
            "metrics": dict(response.metrics),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._redact(entry), ensure_ascii=False) + "\n")
        return entry

    def load(self, limit: int | None = 20) -> list[dict[str, Any]]:
        entries = list(reversed(self._load_chronological()))
        if limit is not None:
            entries = entries[:limit]
        return entries

    def _load_chronological(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def export(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "entries": self.load(limit=None)}

    def delete(self, audit_id: str) -> bool:
        if re.fullmatch(r"audit-[0-9a-f]{12}", audit_id) is None:
            raise ValueError("A valid audit ID is required.")
        entries = self._load_chronological()
        retained = [entry for entry in entries if entry.get("audit_id") != audit_id]
        if len(retained) == len(entries):
            return False
        temporary_path = self.state_dir / f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                for entry in retained:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        return True

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            return re.sub(
                r"(?i)(password|token|api[_ -]?key|secret)\s*[:=]\s*[^\s,;]+",
                r"\1=[REDACTED]",
                value,
            )
        return value
