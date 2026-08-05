"""Experiment registry: the agent's memory across turns and sessions.

One JSON file, append-mostly. Every pipeline stage the agent runs is
recorded with its parameters, metrics, and artifact paths, so the agent
can answer "what have we tried?" and reuse prior work after a restart.
"""

import json
import time
from pathlib import Path


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, entries: list[dict]):
        self.path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def append(self, task_name: str, stage: str, run_dir: str,
               params: dict, metrics: dict) -> str:
        entries = self._load()
        entry_id = f"exp-{len(entries) + 1:04d}"
        entries.append({
            "id": entry_id,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "task": task_name,
            "stage": stage,
            "run_dir": run_dir,
            "params": params,
            "metrics": metrics,
        })
        self._save(entries)
        return entry_id

    def list(self, task_name: str | None = None) -> list[dict]:
        entries = self._load()
        if task_name:
            entries = [e for e in entries if e["task"] == task_name]
        return [
            {"id": e["id"], "time": e["time"], "task": e["task"],
             "stage": e["stage"], "metrics": e["metrics"]}
            for e in entries
        ]

    def get(self, entry_id: str) -> dict | None:
        return next((e for e in self._load() if e["id"] == entry_id), None)
