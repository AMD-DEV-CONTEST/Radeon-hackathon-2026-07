from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LocalMemory:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "memory.json"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def update(self, changes: dict[str, str]) -> dict[str, str]:
        data = self.load()
        data.update({str(key): str(value) for key, value in changes.items() if value})
        self._write_json_atomic(self.path, data)
        return data

    def save_json(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self.state_dir / name
        self._write_json_atomic(path, payload)
        return payload

    def load_json(self, name: str) -> dict[str, Any]:
        path = self.state_dir / name
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
