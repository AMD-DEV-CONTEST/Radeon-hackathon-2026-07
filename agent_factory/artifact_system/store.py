from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class ArtifactStore:
    def __init__(self, *, root: str | Path, allowed_kinds: list[str] | tuple[str, ...]) -> None:
        self.root = Path(root)
        self.allowed_kinds = frozenset(str(kind) for kind in allowed_kinds)
        if not self.allowed_kinds:
            raise ValueError("artifact store requires at least one allowed kind")

    def write_json(self, *, kind: str, relative_path: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.write_text(
            kind=kind,
            relative_path=relative_path,
            content=json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            metadata=metadata,
        )

    def write_text(self, *, kind: str, relative_path: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.write_bytes(
            kind=kind,
            relative_path=relative_path,
            content=content.encode("utf-8"),
            metadata={**dict(metadata or {}), "encoding": "utf-8"},
        )

    def write_bytes(self, *, kind: str, relative_path: str, content: bytes, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self._validate_kind(kind)
        target = self._resolve_relative_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        record = {
            "artifact_id": uuid4().hex,
            "kind": kind,
            "path": str(target),
            "relative_path": str(target.relative_to(self.root.resolve())),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": dict(metadata or {}),
        }
        return record

    def _validate_kind(self, kind: str) -> None:
        if kind not in self.allowed_kinds:
            raise ValueError(f"artifact kind is not allowed: {kind}")

    def _resolve_relative_path(self, relative_path: str) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
            raise ValueError("artifact path must be relative and must not contain current or parent segments")
        root = self.root.resolve()
        target = (root / raw).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("artifact path escapes artifact root") from exc
        return target

class ReportStore:
    def __init__(self, *, artifact_store: ArtifactStore, report_kind: str = "report") -> None:
        self.artifact_store = artifact_store
        self.report_kind = report_kind

    def write_report(self, *, report_id: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        safe_report_id = report_id.strip().replace("/", "_")
        if not safe_report_id:
            raise ValueError("report_id must not be empty")
        return self.artifact_store.write_json(
            kind=self.report_kind,
            relative_path=f"reports/{safe_report_id}.json",
            payload=payload,
            metadata=metadata,
        )
