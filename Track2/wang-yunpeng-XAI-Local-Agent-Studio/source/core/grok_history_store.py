"""Grok Build 运行历史存储（XAI 自有，零依赖 sqlite3）。

与 ChatConsole 的 core/session_store.py 同款设计：单文件 SQLite，WAL 模式，
落盘在 ~/.xai/grok_history.db。每条记录 = 一次 /api/grok/run 的成功/失败产出，
前端可按「历史 ▼」抽屉列出、点开恢复（task + 完整 result_json + 画布）、删除。

设计要点：
- 这是 XAI 自己拥有的历史，区别于 grok 二进制自管的 `grok sessions list`
  （后者只给原始表格，无法恢复 XAI 侧的产出/画布）。
- 落盘失败一律不阻断主执行链路（由调用方 try/except 包裹，pass）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional


def _default_db_path() -> str:
    home = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "grok_history.db")


class GrokHistoryStore:
    """Grok Build 运行历史持久化（~/.xai/grok_history.db）。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _default_db_path()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id               TEXT PRIMARY KEY,
                ts               INTEGER NOT NULL,
                task             TEXT NOT NULL,
                model            TEXT,
                ok               INTEGER NOT NULL DEFAULT 1,
                summary          TEXT,
                result_json      TEXT,
                grok_session_id TEXT
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts DESC)")
        self._conn.commit()

    def add_run(
        self,
        task: str,
        model: Optional[str],
        ok: bool,
        summary: str,
        result_json: Dict[str, Any],
        grok_session_id: Optional[str] = None,
    ) -> str:
        """追加一条运行记录，返回新生成的 id。"""
        rid = uuid.uuid4().hex
        ts = int(time.time())
        self._conn.execute(
            """
            INSERT INTO runs (id, ts, task, model, ok, summary, result_json, grok_session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                ts,
                task,
                model or None,
                1 if ok else 0,
                summary or None,
                json.dumps(result_json, ensure_ascii=False),
                grok_session_id or None,
            ),
        )
        self._conn.commit()
        return rid

    def list_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出最近运行（新→旧），不含完整 result_json。"""
        cur = self._conn.execute(
            """
            SELECT id, ts, task, model, ok, summary, grok_session_id
            FROM runs ORDER BY ts DESC LIMIT ?
            """,
            (limit,),
        )
        cols = ["id", "ts", "task", "model", "ok", "summary", "grok_session_id"]
        out: List[Dict[str, Any]] = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            rec["ok"] = int(rec["ok"])
            out.append(rec)
        return out

    def get_run(self, rid: str) -> Optional[Dict[str, Any]]:
        """按 id 取完整记录（含 result_json，已解析为 dict）。"""
        cur = self._conn.execute(
            """
            SELECT id, ts, task, model, ok, summary, result_json, grok_session_id
            FROM runs WHERE id = ?
            """,
            (rid,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = ["id", "ts", "task", "model", "ok", "summary", "result_json", "grok_session_id"]
        rec = dict(zip(cols, row))
        rec["ok"] = int(rec["ok"])
        try:
            rec["result_json"] = json.loads(rec["result_json"]) if rec["result_json"] else {}
        except Exception:
            rec["result_json"] = {}
        return rec

    def delete_run(self, rid: str) -> bool:
        """删除一条记录，返回是否真的删到了。"""
        cur = self._conn.execute("DELETE FROM runs WHERE id = ?", (rid,))
        self._conn.commit()
        return cur.rowcount > 0


_STORE: Optional[GrokHistoryStore] = None


def get_grok_history_store() -> GrokHistoryStore:
    """进程内单例（与 engine/model_registry 同款惰性获取）。"""
    global _STORE
    if _STORE is None:
        _STORE = GrokHistoryStore()
    return _STORE
