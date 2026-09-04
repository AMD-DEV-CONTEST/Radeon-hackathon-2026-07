"""Load immutable, provenance-bearing scenario-library entries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ScenarioLibrary:
    """A directory-backed collection sharing one explicit library version."""

    def __init__(self, version: str, entries: dict[str, dict[str, Any]]) -> None:
        self.version = version
        self._entries = entries

    @classmethod
    def from_directory(cls, directory: str | Path) -> "ScenarioLibrary":
        entries: dict[str, dict[str, Any]] = {}
        versions: set[str] = set()
        paths = sorted(Path(directory).glob("*.json"))
        if not paths:
            raise ValueError("scenario library contains no JSON entries")
        required = {
            "schema_version", "library_version", "scenario_classification",
            "parameter_sources", "expected_qualitative_behavior", "transport",
        }
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"scenario entry must be an object: {path.name}")
            missing = required - set(payload)
            if missing:
                raise ValueError(f"missing scenario-library field: {sorted(missing)[0]}")
            transport = payload["transport"]
            if not isinstance(transport, dict) or not isinstance(transport.get("scenario_id"), str):
                raise ValueError("scenario entry requires transport.scenario_id")
            scenario_id = transport["scenario_id"]
            if scenario_id in entries:
                raise ValueError(f"duplicate scenario_id: {scenario_id}")
            entries[scenario_id] = payload
            versions.add(str(payload["library_version"]))
        if len(versions) != 1:
            raise ValueError("scenario entries must share one library_version")
        return cls(versions.pop(), entries)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, scenario_id: str) -> dict[str, Any]:
        if scenario_id not in self._entries:
            raise KeyError(scenario_id)
        return json.loads(json.dumps(self._entries[scenario_id]))
