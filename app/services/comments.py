"""
Phase H — 评论与 @提及服务

支持对任务、风险、报告段落的多实体评论；
评论中可 @提及项目成员。
"""

from __future__ import annotations

import re
import sqlite3
import uuid


_MENTION_RE = re.compile(r"@(\S+)")


class CommentService:
    """Manage comments and @mentions."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_comment(
        self,
        project_id: str,
        entity_type: str,
        entity_id: str,
        author_id: str,
        body: str,
        parent_id: str | None = None,
        mentions: list[str] | None = None,
    ) -> dict:
        """Create a comment and return it."""
        conn = self._connect()
        try:
            cid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO comment (id, project_id, entity_type, entity_id, author_id, body, parent_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, project_id, entity_type, entity_id, author_id, body, parent_id),
            )

            # Record mentions
            if mentions:
                for uname in mentions:
                    user = conn.execute(
                        "SELECT id FROM user_account WHERE username = ? AND is_active = 1",
                        (uname.strip(),),
                    ).fetchone()
                    if user:
                        conn.execute(
                            "INSERT OR IGNORE INTO mention (id, comment_id, mentioned_user_id) VALUES (?, ?, ?)",
                            (str(uuid.uuid4()), cid, user["id"]),
                        )

            conn.commit()
            return self._get_comment_dict(conn, cid)
        finally:
            conn.close()

    def update_comment(self, comment_id: str, body: str) -> dict | None:
        """Update a comment body."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE comment SET body = ?, updated_at = datetime('now') WHERE id = ?",
                (body, comment_id),
            )
            conn.commit()
            return self._get_comment_dict(conn, comment_id)
        finally:
            conn.close()

    def delete_comment(self, comment_id: str) -> bool:
        """Delete a comment."""
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM comment WHERE id = ?", (comment_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def resolve_comment(self, comment_id: str, resolved: bool = True) -> dict | None:
        """Mark a comment as resolved/unresolved."""
        conn = self._connect()
        try:
            v = 1 if resolved else 0
            conn.execute(
                "UPDATE comment SET is_resolved = ?, updated_at = datetime('now') WHERE id = ?",
                (v, comment_id),
            )
            conn.commit()
            return self._get_comment_dict(conn, comment_id)
        finally:
            conn.close()

    def get_comment(self, comment_id: str) -> dict | None:
        conn = self._connect()
        try:
            return self._get_comment_dict(conn, comment_id)
        finally:
            conn.close()

    def list_comments(
        self, project_id: str, entity_type: str, entity_id: str
    ) -> list[dict]:
        """List all comments for an entity, threaded."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT c.*, u.username as author_name FROM comment c "
                "JOIN user_account u ON c.author_id = u.id "
                "WHERE c.project_id = ? AND c.entity_type = ? AND c.entity_id = ? "
                "ORDER BY c.created_at ASC",
                (project_id, entity_type, entity_id),
            ).fetchall()

            # Fetch mentions for all these comments
            comment_ids = [r["id"] for r in rows]
            mentions_map: dict[str, list[str]] = {}
            if comment_ids:
                placeholders = ",".join("?" for _ in comment_ids)
                mention_rows = conn.execute(
                    f"SELECT m.comment_id, u.username FROM mention m "
                    f"JOIN user_account u ON m.mentioned_user_id = u.id "
                    f"WHERE m.comment_id IN ({placeholders})",
                    comment_ids,
                ).fetchall()
                for mr in mention_rows:
                    mentions_map.setdefault(mr["comment_id"], []).append(mr["username"])

            comments = []
            children_map: dict[str, list[dict]] = {}
            for r in rows:
                entry = {
                    "id": r["id"],
                    "project_id": r["project_id"],
                    "entity_type": r["entity_type"],
                    "entity_id": r["entity_id"],
                    "author_id": r["author_id"],
                    "author_name": r["author_name"],
                    "parent_id": r["parent_id"],
                    "body": r["body"],
                    "is_resolved": bool(r["is_resolved"]),
                    "mentions": mentions_map.get(r["id"], []),
                    "replies": [],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
                if r["parent_id"] is None:
                    comments.append(entry)
                else:
                    children_map.setdefault(r["parent_id"], []).append(entry)
            # Nest replies
            for c in comments:
                c["replies"] = children_map.get(c["id"], [])

            return comments
        finally:
            conn.close()

    def extract_mentions(self, body: str) -> list[str]:
        """Extract @mentioned usernames from comment body."""
        return _MENTION_RE.findall(body)

    def record_mentions(self, comment_id: str, mentioned_usernames: list[str]) -> int:
        """Record @mentions for a comment. Returns count of mentions created."""
        conn = self._connect()
        count = 0
        try:
            for uname in mentioned_usernames:
                user = conn.execute(
                    "SELECT id FROM user_account WHERE username = ? AND is_active = 1",
                    (uname.strip(),),
                ).fetchone()
                if user:
                    conn.execute(
                        "INSERT OR IGNORE INTO mention (id, comment_id, mentioned_user_id) VALUES (?, ?, ?)",
                        (str(uuid.uuid4()), comment_id, user["id"]),
                    )
                    count += 1
            conn.commit()
            return count
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_comment_dict(self, conn: sqlite3.Connection, comment_id: str) -> dict | None:
        row = conn.execute(
            "SELECT c.*, u.username as author_name FROM comment c "
            "JOIN user_account u ON c.author_id = u.id "
            "WHERE c.id = ?",
            (comment_id,),
        ).fetchone()
        if row is None:
            return None
        mention_rows = conn.execute(
            "SELECT u.username FROM mention m "
            "JOIN user_account u ON m.mentioned_user_id = u.id "
            "WHERE m.comment_id = ?",
            (comment_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "author_id": row["author_id"],
            "author_name": row["author_name"],
            "parent_id": row["parent_id"],
            "body": row["body"],
            "is_resolved": bool(row["is_resolved"]),
            "mentions": [m["username"] for m in mention_rows],
            "replies": [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
