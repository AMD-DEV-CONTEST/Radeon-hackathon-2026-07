from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ReplayManifest:
    tool: str
    selected_root: str
    metadata_status: str
    qualifies_hydration: bool
    quarantine_only: bool
    task_image: str = ""
    local_replay_command: str = ""
    verifier_mode: str = ""
    benchmark_provenance: dict[str, Any] = field(default_factory=dict)
    artifact_source_candidates: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_replay_manifest(manifest: ReplayManifest, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{_safe(manifest.tool)}.replay_manifest.json"
    path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]
