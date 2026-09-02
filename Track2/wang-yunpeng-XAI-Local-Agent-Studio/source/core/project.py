"""Project 管理器（参考 Orbital "Memory is the product" 理念）。

Project 是 7 层记忆的**作用域**——每条记忆带 project_id 标签。
切换 Project → 记忆按作用域隔离；切回 → 记忆召回。
不同 Project 之间的记忆不互相污染。

设计原则：
- 不在 memory_core 里新增"项目层"（不破坏宪法）
- 而是每条记忆的 meta 字段带 project_id → store/query 加 project 过滤
- Project 本身的数据存到 ~/.xai/projects.db（独立 SQLite）
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, List


PROJECTS_DB = os.path.join(os.environ.get("XAI_HOME", os.path.expanduser("~/.xai")), "projects.db")


@dataclass
class Project:
    id: str
    name: str
    description: str = ""
    workspace: str = ""
    instructions: str = ""
    budget: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ProjectManager:
    """Project 生命周期管理。"""

    def __init__(self, db_path: str = PROJECTS_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # RLock（可重入）：current()/create() 会在持有锁时调用 self.get()，
        # 若用非重入 Lock 会自死锁（#12 根因：current() 卡死 → /api/status
        # 的 project 字段为 null、/api/projects 卡死、记忆写入被静默丢弃）。
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._current_id: Optional[str] = None

    def _init_schema(self):
        with self._lock:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
                workspace TEXT DEFAULT '', instructions TEXT DEFAULT '', budget INTEGER DEFAULT 0,
                created_at REAL, updated_at REAL
            )""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_project_name ON projects(name)")
            self._conn.commit()
        self._ensure_default()

    def _ensure_default(self):
        with self._lock:
            row = self._conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
            if not row:
                pid = f"proj:{uuid.uuid4().hex[:8]}"
                self._conn.execute(
                    "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?,?,?,?)",
                    (pid, "默认工作区", time.time(), time.time()),
                )
                self._conn.commit()
                self._current_id = pid

    def create(self, name: str, description: str = "", workspace: str = "",
               instructions: str = "", budget: int = 0) -> Project:
        with self._lock:
            pid = f"proj:{uuid.uuid4().hex[:8]}"
            now = time.time()
            self._conn.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?)",
                (pid, name.strip(), description.strip(), workspace.strip(),
                 instructions.strip(), budget, now, now),
            )
            self._conn.commit()
            return self.get(pid)

    def delete(self, project_id: str) -> bool:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM projects").fetchall()
            if len(rows) <= 1:
                return False  # 最少保留一个
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._conn.commit()
            if self._current_id == project_id:
                first = self._conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
                self._current_id = first["id"] if first else None
            return True

    def get(self, project_id: str) -> Optional[Project]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                return None
            return Project(**{k: row[k] for k in row.keys()})

    def list(self) -> List[Project]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
            return [Project(**{k: r[k] for k in r.keys()}) for r in rows]

    def current(self) -> Optional[Project]:
        with self._lock:
            if self._current_id:
                return self.get(self._current_id)
            row = self._conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
            if row:
                self._current_id = row["id"]
                return self.get(row["id"])
            return None

    def activate(self, project_id: str) -> Optional[Project]:
        p = self.get(project_id)
        if p:
            with self._lock:
                self._current_id = project_id
                self._conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (time.time(), project_id))
                self._conn.commit()
        return p

    def update(self, project_id: str, **kwargs) -> Optional[Project]:
        p = self.get(project_id)
        if not p:
            return None
        with self._lock:
            sets = []
            vals = []
            for k, v in kwargs.items():
                if hasattr(p, k) and k != "id":
                    sets.append(f"{k}=?")
                    vals.append(v)
            if not sets:
                return p
            vals.append(time.time())
            vals.append(project_id)
            self._conn.execute(f"UPDATE projects SET {','.join(sets)},updated_at=? WHERE id=?", vals)
            self._conn.commit()
            return self.get(project_id)

    def close(self):
        with self._lock:
            self._conn.close()


_singleton: Optional[ProjectManager] = None
_singleton_lock = threading.Lock()


def default_project_manager() -> ProjectManager:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ProjectManager()
    return _singleton
