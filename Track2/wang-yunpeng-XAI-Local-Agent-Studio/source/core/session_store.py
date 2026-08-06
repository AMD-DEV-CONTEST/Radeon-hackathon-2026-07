"""XAI 会话历史存储

对标 ChatGPT / dify 的多轮对话上下文：每个 session 维护消息历史，
持久化到 SQLite，保证进程重启后历史不丢、多线程安全。

历史以 OpenAI messages 格式存储（role/content），推理时整体喂给模型，
实现真正的多轮连贯对话。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional


class SessionStore:
    """会话历史存储（SQLite，WAL 模式，线程安全）"""

    def __init__(self, home: str):
        self._db_path = os.path.join(home, "sessions.db")
        self._lock = threading.Lock()
        os.makedirs(home, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        # check_same_thread=False 配合锁保证多线程安全
        conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        ts REAL NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session, id)")
                conn.commit()
            finally:
                conn.close()

    def add(self, session: str, role: str, content: str):
        """追加一条消息。"""
        if not content:
            return
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO messages (session, role, content, ts) VALUES (?,?,?,?)",
                    (session, role, content, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

    def get_history(self, session: str, limit: int = 24) -> List[Dict[str, str]]:
        """返回最近 limit 条历史，OpenAI messages 格式。

        limit 控制上下文窗口，避免无限增长撑爆 prompt。
        """
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "SELECT role, content FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
                    (session, limit),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        # 倒序还原时间顺序
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def list_sessions(self) -> List[Dict[str, str]]:
        """列出所有会话及其最新一条消息（用于前端会话列表）。
        返回格式对齐前端 SessionInfo：id/title/created_at/last_active_at/message_count"""
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    """
                    SELECT session, role, content, ts FROM messages
                    WHERE id IN (SELECT MAX(id) FROM messages GROUP BY session)
                    ORDER BY ts DESC
                    """,
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        result = []
        for s, r, c, t in rows:
            result.append({
                "id": s,
                "session": s,
                "title": c[:60] if c else s,
                "last_role": r,
                "last_content": c[:120],
                "last_active_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)),
                "message_count": self.count(s),
                "ts": t,
            })
        return result

    def clear(self, session: str):
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM messages WHERE session=?", (session,))
                conn.commit()
            finally:
                conn.close()

    def count(self, session: str) -> int:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute("SELECT COUNT(*) FROM messages WHERE session=?", (session,))
                return cur.fetchone()[0]
            finally:
                conn.close()
