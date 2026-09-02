"""XAI 底座记忆内核（OpenClaw+Hermes 内存级耦合的本地等价实现）。

这是「底座」的记忆部分：一个**单一事实源**，TrueAgent 式 8 层记忆 + 元认知反思层
+ 失败修正记忆。OpenClaw 执行网关与 Hermes 进化内核共享它 —— 即「内存级耦合」，
不是 MCP 外部拼接。

设计要点：
- 纯本地 SQLite（~/.xai/memory.db），无云、无遥测、可完全离线。
- 8 层：working(工作上下文) / short_term(短期) / long_term(长期事实)
       / anchor(锚点·稳定核心) / reflection(反思·元认知) / causal(因果链)
       / user_profile(用户画像·人格元记忆) + failure_correction(失败修正)。
- 每条记忆带 `engine` 标签（xai/openclaw/hermes/grok_build/...），支持跨引擎查询，
  消除多 Agent 记忆割裂（对应我们「统一记忆单一事实源」优势根）。
- 模型无关：不依赖任何大模型即可读写；模型只消费这里的数据。

本模块是「底座记忆内核」的真实实现，经 SubstratePort 暴露给 XAI 引擎。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Layer(str, Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    ANCHOR = "anchor"
    REFLECTION = "reflection"
    CAUSAL = "causal"
    USER_PROFILE = "user_profile"
    FAILURE_CORRECTION = "failure_correction"
    SKILL = "skill"          # Phase 2: 可复用技能积累


ALL_LAYERS = [l.value for l in Layer]


def _default_db_path() -> str:
    base = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "memory.db")


@dataclass
class MemoryEntry:
    id: int
    layer: str
    engine: str
    key: str
    value: str
    importance: float
    meta: dict = field(default_factory=dict)
    created_at: float = 0.0
    accessed_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "layer": self.layer, "engine": self.engine,
            "key": self.key, "value": self.value, "importance": self.importance,
            "meta": self.meta, "created_at": self.created_at, "accessed_at": self.accessed_at,
        }


class MemoryCore:
    """本地 8 层元认知记忆内核（单一事实源 · 含 failure_correction 我们特有层）。

    线程安全：单连接 + 锁，适配 http.server 多线程。
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _default_db_path()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # RLock（可重入）：get() 持锁后内部调 touch() 会再次加锁，
        # 普通 Lock 不可重入会自死锁（2026-07-24 清理复盘时真机抓出）
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout=5000")  # 多进程争锁时等待而非卡死(A10)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    layer TEXT NOT NULL,
                    engine TEXT NOT NULL DEFAULT 'xai',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    meta TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL
                )"""
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_layer ON memory(layer)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_engine ON memory(engine)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_key ON memory(key)")
            self._conn.commit()

    # ---------- 写入 ----------
    def store(self, layer: str, key: str, value: str, engine: str = "xai",
              importance: float = 0.5, meta: Optional[dict] = None,
              project_id: Optional[str] = None) -> int:
        if layer not in ALL_LAYERS:
            raise ValueError(f"未知记忆层: {layer}; 合法层: {ALL_LAYERS}")
        meta = dict(meta or {})
        if project_id is not None:
            meta["project_id"] = project_id
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO memory (layer, engine, key, value, importance, meta, created_at, accessed_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (layer, engine, key, value, importance, json.dumps(meta), now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update(self, entry_id: int, value: Optional[str] = None, importance: Optional[float] = None) -> None:
        with self._lock:
            if value is not None:
                self._conn.execute("UPDATE memory SET value=?, accessed_at=? WHERE id=?",
                                   (value, time.time(), entry_id))
            if importance is not None:
                self._conn.execute("UPDATE memory SET importance=? WHERE id=?", (importance, entry_id))
            self._conn.commit()

    def touch(self, entry_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE memory SET accessed_at=? WHERE id=?", (time.time(), entry_id))
            self._conn.commit()

    def delete(self, entry_id: int) -> bool:
        """删除一条记忆条目。返回 True 表示删除成功，False 表示条目不存在。"""
        with self._lock:
            cur = self._conn.execute("DELETE FROM memory WHERE id=?", (entry_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- 查询 ----------
    def get(self, layer: str, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory WHERE layer=? AND key=? ORDER BY importance DESC LIMIT 1",
                (layer, key),
            ).fetchone()
            if row is None:
                return None
            self.touch(row["id"])
            return self._row_to_entry(row)

    def query(self, layer: Optional[str] = None, engine: Optional[str] = None,
              keyword: Optional[str] = None, project_id: Optional[str] = None,
              limit: int = 20, offset: int = 0, order: str = "importance") -> list[MemoryEntry]:
        """检索记忆条目。

        order:
          "importance" — 重要性优先（召回/注入用，默认，保持既有行为不变）
          "recent"     — 最新写入优先（记忆中心列表用）

        新增 order/offset 的原因（2026-08-04）：此前恒按 importance DESC 且无分页，
        记忆中心页只能看到"重要性最高的前 N 条"。后果有二：
          1. 用户刚写入的低重要性记忆在列表里根本看不见，像是没存进去；
          2. 排在 N 名之外的条目永远拿不到 id，而改/删接口按 id 操作，
             等于这些记忆被永久锁死，无法编辑也无法删除。
        """
        sql = "SELECT * FROM memory WHERE 1=1"
        args: list = []
        if layer:
            sql += " AND layer=?"; args.append(layer)
        if engine:
            sql += " AND engine=?"; args.append(engine)
        if keyword:
            sql += " AND (key LIKE ? OR value LIKE ?)"; args.append(f"%{keyword}%"); args.append(f"%{keyword}%")
        # project_id 过滤：json.dumps 在冒号后带空格（如 "project_id": "X"），
        # 直接 LIKE '"project_id":"X"' 会因空格漏配。先粗筛含 project_id 的行，再精确解析 meta 匹配。
        if project_id:
            sql += " AND meta LIKE ?"; args.append("%project_id%")
        if order == "recent":
            sql += " ORDER BY created_at DESC, id DESC"
        else:
            sql += " ORDER BY importance DESC, accessed_at DESC"
        sql += " LIMIT ? OFFSET ?"
        args.append(limit)
        args.append(max(0, int(offset or 0)))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
            entries = [self._row_to_entry(r) for r in rows]
        if project_id:
            entries = [e for e in entries if (e.meta or {}).get("project_id") == project_id]
        return entries

    def count(self, layer: Optional[str] = None, engine: Optional[str] = None,
              keyword: Optional[str] = None) -> int:
        """符合条件的记忆总条数（供列表页分页用）。"""
        sql = "SELECT COUNT(*) FROM memory WHERE 1=1"
        args: list = []
        if layer:
            sql += " AND layer=?"; args.append(layer)
        if engine:
            sql += " AND engine=?"; args.append(engine)
        if keyword:
            sql += " AND (key LIKE ? OR value LIKE ?)"; args.append(f"%{keyword}%"); args.append(f"%{keyword}%")
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        return int(row[0]) if row else 0

    def recall(self, keyword: str, limit: int = 10, project_id: Optional[str] = None) -> list[MemoryEntry]:
        """跨层语义召回（子串 + 重要性排序）。project_id 实现项目隔离。"""
        return self.query(keyword=keyword, project_id=project_id, limit=limit)

    def query_cross_engine(self, engine: str, limit: int = 50) -> list[MemoryEntry]:
        """跨引擎查询：消除多 Agent 记忆割裂的关键接口。"""
        return self.query(engine=engine, limit=limit)

    def record_failure(self, task: str, error: str, correction: str = "", engine: str = "xai",
                       meta: Optional[dict] = None, project_id: Optional[str] = None) -> int:
        """失败修正记忆（Hermes 扩展层 / 第8层·我们特有）：记录失败与纠正，供后续 self-refine。

        meta 可附结构化诊断（error_type / root_cause_hypothesis / recovery_action / model 等），
        让第8层产出"可复用教训"而非纯字符串。向后兼容：substrate.py 原调用 correction="" 仍可用。
        """
        payload = json.dumps({"task": task, "error": error, "correction": correction}, ensure_ascii=False)
        m = {"kind": "failure_correction"}
        if meta:
            m.update(meta)
        return self.store(Layer.FAILURE_CORRECTION.value, f"fail:{int(time.time())}", payload,
                          engine=engine, importance=0.8, meta=m, project_id=project_id)

    def reflect(self, limit: int = 20) -> dict:
        """元认知反思层：汇总近期短期记忆 + 失败修正，产出可消费的结构化反思。"""
        recent = self.query(layer=Layer.SHORT_TERM.value, limit=limit)
        failures = self.query(layer=Layer.FAILURE_CORRECTION.value, limit=5)
        reflections = self.query(layer=Layer.REFLECTION.value, limit=5)
        summary = {
            "recent_interactions": [e.to_dict() for e in recent],
            "failure_patterns": [json.loads(e.value) for e in failures if e.value.startswith("{")],
            "prior_reflections": [e.value for e in reflections],
            "generated_at": time.time(),
        }
        # 把这次反思落回 reflection 层（重要性高）
        self.store(Layer.REFLECTION.value, f"reflect:{int(time.time())}",
                   json.dumps(summary, ensure_ascii=False), engine="xai", importance=0.7,
                   meta={"kind": "metacognitive_reflection"})
        return summary

    def consolidate(self) -> int:
        """记忆巩固：把高重要性的短期记忆提升为长期记忆（防膨胀）。"""
        moved = 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory WHERE layer=? AND importance>=? LIMIT 50",
                (Layer.SHORT_TERM.value, 0.7),
            ).fetchall()
            for r in rows:
                self._conn.execute(
                    "UPDATE memory SET layer=? WHERE id=?", (Layer.LONG_TERM.value, r["id"])
                )
                moved += 1
            self._conn.commit()
        return moved

    def stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT layer, COUNT(*) AS c FROM memory GROUP BY layer"
            ).fetchall()
        counts = {r["layer"]: r["c"] for r in rows}
        # 宪法要求 8 层完整：缺失层补 0，保证前端 MemoryStats 对齐 8 层（而非仅返回有数据的层）
        return {layer: counts.get(layer, 0) for layer in ALL_LAYERS}

    def _row_to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        try:
            meta = json.loads(row["meta"])
        except Exception:
            meta = {}
        return MemoryEntry(
            id=row["id"], layer=row["layer"], engine=row["engine"], key=row["key"],
            value=row["value"], importance=row["importance"], meta=meta,
            created_at=row["created_at"], accessed_at=row["accessed_at"],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# 便捷单例（进程级共享，符合「内存级单一事实源」）
_default_core: Optional[MemoryCore] = None
_default_core_lock = threading.Lock()


def default_core() -> MemoryCore:
    global _default_core
    if _default_core is None:
        with _default_core_lock:
            if _default_core is None:
                _default_core = MemoryCore()
    return _default_core
