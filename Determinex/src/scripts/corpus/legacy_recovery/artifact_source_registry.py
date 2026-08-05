from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ArtifactSource:
    name: str
    type: str
    trust_level: str
    allowed_for: list[str] = field(default_factory=list)
    requires_digest: bool = False
    requires_revision_pin: bool = False
    requires_license: bool = False
    requires_security_scan: bool = False


class ArtifactSourceRegistry:
    def __init__(self, path: Path = Path("assurance/config/artifact_sources.json")) -> None:
        self.path = path
        self.sources = self._load(path)

    def get(self, name: str) -> ArtifactSource | None:
        return self.sources.get(name)

    @staticmethod
    def _load(path: Path) -> dict[str, ArtifactSource]:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, ArtifactSource] = {}
        for row in data.get("sources") or []:
            if isinstance(row, dict) and row.get("name"):
                out[str(row["name"])] = _source(row)
        return out


def _source(row: dict[str, Any]) -> ArtifactSource:
    return ArtifactSource(
        name=str(row.get("name") or ""),
        type=str(row.get("type") or "unknown"),
        trust_level=str(row.get("trust_level") or "unknown"),
        allowed_for=[str(item) for item in (row.get("allowed_for") or [])],
        requires_digest=bool(row.get("requires_digest")),
        requires_revision_pin=bool(row.get("requires_revision_pin")),
        requires_license=bool(row.get("requires_license")),
        requires_security_scan=bool(row.get("requires_security_scan")),
    )
