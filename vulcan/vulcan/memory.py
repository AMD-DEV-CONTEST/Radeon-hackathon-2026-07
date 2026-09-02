"""Persistent agent memory: distilled notes that survive across sessions."""
from __future__ import annotations

import sqlite3
import time

from .config import Config


class Memory:
    def __init__(self, cfg: Config, project: str):
        self.db = sqlite3.connect(cfg.data_dir / "memory.sqlite3")
        self.project = project
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            " id INTEGER PRIMARY KEY, project TEXT, ts REAL, note TEXT)"
        )

    def remember(self, note: str) -> None:
        self.db.execute(
            "INSERT INTO notes (project, ts, note) VALUES (?,?,?)",
            (self.project, time.time(), note),
        )
        self.db.commit()

    def recall(self, limit: int = 20) -> list[str]:
        rows = self.db.execute(
            "SELECT note FROM notes WHERE project=? ORDER BY ts DESC LIMIT ?",
            (self.project, limit),
        ).fetchall()
        return [r[0] for r in reversed(rows)]
