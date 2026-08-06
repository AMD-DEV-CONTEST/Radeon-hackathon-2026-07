"""
SQLite 审计日志 — 防篡改哈希链。
所有关键操作记录到 SQLite，形成不可篡改的审计链。
"""
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List


class AuditLogger:
    """哈希链审计日志。每条记录包含上一条的哈希，防止篡改。"""

    DB_PATH = None  # 运行时自动设置

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "audit.db")
        AuditLogger.DB_PATH = db_path

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(AuditLogger.DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    current_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(event_type)
            """)
            conn.commit()

    def log(self, task_id: str, event_type: str, data: Dict[str, Any]) -> str:
        """
        记录一条审计日志。
        
        Args:
            task_id: 任务唯一标识
            event_type: 事件类型 (quote/expert_panel/veto/ceo_decision)
            data: 事件数据（标准 JSON dict）
        
        Returns:
            当前记录的哈希值
        """
        prev_hash = self._last_hash()
        event_json = json.dumps(data, ensure_ascii=False, sort_keys=True)
        current_hash = self._compute_hash(task_id, event_type, event_json, prev_hash)

        with sqlite3.connect(AuditLogger.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO audit_log (task_id, event_type, event_data, prev_hash, current_hash) VALUES (?, ?, ?, ?, ?)",
                (task_id, event_type, event_json, prev_hash, current_hash)
            )
            conn.commit()

        return current_hash

    def _last_hash(self) -> str:
        """获取最后一条记录的哈希。"""
        with sqlite3.connect(AuditLogger.DB_PATH) as conn:
            row = conn.execute(
                "SELECT current_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else "0" * 64  # 创世哈希

    @staticmethod
    def _compute_hash(task_id: str, event_type: str, data_json: str, prev_hash: str) -> str:
        content = f"{task_id}|{event_type}|{data_json}|{prev_hash}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def verify_chain(self) -> Dict[str, Any]:
        """验证审计链完整性。"""
        with sqlite3.connect(AuditLogger.DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id, task_id, event_type, event_data, prev_hash, current_hash FROM audit_log ORDER BY id"
            ).fetchall()

        broken_at = []
        for i, row in enumerate(rows):
            expected = self._compute_hash(row[1], row[2], row[3], rows[i-1][5] if i > 0 else "0" * 64)
            if expected != row[5]:
                broken_at.append(row[0])

        return {
            "total_records": len(rows),
            "is_valid": len(broken_at) == 0,
            "broken_at": broken_at,
            "verified_at": datetime.now().isoformat(),
        }

    def query(self, task_id: Optional[str] = None, event_type: Optional[str] = None,
              limit: int = 20) -> List[Dict[str, Any]]:
        """查询审计日志。"""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(AuditLogger.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_report(self) -> str:
        """标准 JSON 审计报告。"""
        report = {
            "db_path": AuditLogger.DB_PATH,
            **self.verify_chain(),
            "recent": self.query(limit=10),
        }
        # 截断 event_data 以避免过大
        for r in report["recent"]:
            if len(r.get("event_data", "")) > 200:
                r["event_data"] = r["event_data"][:200] + "..."
        return json.dumps(report, ensure_ascii=False, indent=2)
