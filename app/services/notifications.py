"""
Phase H — 通知收件箱服务

站内通知的创建、查询和标记已读。
"""

from __future__ import annotations

import sqlite3
import uuid


class NotificationService:
    """In-app notification inbox."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_notification(
        self,
        recipient_id: str,
        kind: str,
        title: str,
        body: str = "",
        link: str = "",
    ) -> dict:
        """Create a notification and return it."""
        conn = self._connect()
        try:
            nid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO notification (id, recipient_id, kind, title, body, link) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nid, recipient_id, kind, title, body, link),
            )
            conn.commit()
            return self._row_to_dict(
                conn.execute("SELECT * FROM notification WHERE id = ?", (nid,)).fetchone()
            )
        finally:
            conn.close()

    def mark_read(self, notification_id: str, user_id: str) -> dict | None:
        """Mark a single notification as read."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE notification SET is_read = 1 WHERE id = ? AND recipient_id = ?",
                (notification_id, user_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM notification WHERE id = ?", (notification_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def mark_all_read(self, user_id: str) -> int:
        """Mark all notifications for a user as read. Returns count updated."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE notification SET is_read = 1 WHERE recipient_id = ? AND is_read = 0",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def list_notifications(
        self, user_id: str, unread_only: bool = False, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """List notifications for a user."""
        conn = self._connect()
        try:
            where = "recipient_id = ?"
            params: list = [user_id]
            if unread_only:
                where += " AND is_read = 0"
            rows = conn.execute(
                f"SELECT * FROM notification WHERE {where} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def unread_count(self, user_id: str) -> int:
        """Get the number of unread notifications."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM notification "
                "WHERE recipient_id = ? AND is_read = 0",
                (user_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "recipient_id": row["recipient_id"],
            "kind": row["kind"],
            "title": row["title"],
            "body": row["body"],
            "link": row["link"],
            "is_read": bool(row["is_read"]),
            "created_at": row["created_at"],
        }
