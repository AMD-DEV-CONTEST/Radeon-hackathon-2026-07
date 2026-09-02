"""
Phase H — 项目成员管理服务

管理项目成员关系、角色分配和权限查询。
"""

from __future__ import annotations

import sqlite3
import uuid


class MembershipService:
    """Manage project membership and roles."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Member CRUD
    # ------------------------------------------------------------------

    def add_member(self, project_id: str, user_id: str, role: str) -> dict:
        """Add a member to a project. Returns the membership record."""
        conn = self._connect()
        try:
            # Check user exists
            user = conn.execute(
                "SELECT id FROM user_account WHERE id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
            if user is None:
                raise ValueError("User not found")

            # Check not already a member
            existing = conn.execute(
                "SELECT id FROM project_member WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if existing:
                raise ValueError("Member already exists")

            mid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO project_member (id, project_id, user_id, role) VALUES (?, ?, ?, ?)",
                (mid, project_id, user_id, role),
            )
            conn.commit()
            return self._row_to_member(
                conn.execute(
                    "SELECT pm.*, u.username, u.display_name "
                    "FROM project_member pm JOIN user_account u ON pm.user_id = u.id "
                    "WHERE pm.id = ?",
                    (mid,),
                ).fetchone()
            )
        finally:
            conn.close()

    def update_member_role(self, project_id: str, user_id: str, role: str) -> dict:
        """Update a member's role."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE project_member SET role = ? WHERE project_id = ? AND user_id = ?",
                (role, project_id, user_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT pm.*, u.username, u.display_name "
                "FROM project_member pm JOIN user_account u ON pm.user_id = u.id "
                "WHERE pm.project_id = ? AND pm.user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("Member not found")
            return self._row_to_member(row)
        finally:
            conn.close()

    def remove_member(self, project_id: str, user_id: str) -> bool:
        """Remove a member from a project."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM project_member WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_member(self, project_id: str, user_id: str) -> dict | None:
        """Get a single member record."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT pm.*, u.username, u.display_name "
                "FROM project_member pm JOIN user_account u ON pm.user_id = u.id "
                "WHERE pm.project_id = ? AND pm.user_id = ?",
                (project_id, user_id),
            ).fetchone()
            return self._row_to_member(row) if row else None
        finally:
            conn.close()

    def list_members(self, project_id: str) -> list[dict]:
        """List all members of a project."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT pm.*, u.username, u.display_name "
                "FROM project_member pm JOIN user_account u ON pm.user_id = u.id "
                "WHERE pm.project_id = ? "
                "ORDER BY CASE pm.role "
                "  WHEN 'admin' THEN 1 WHEN 'pm' THEN 2 WHEN 'member' THEN 3 WHEN 'guest' THEN 4 END",
                (project_id,),
            ).fetchall()
            return [self._row_to_member(r) for r in rows]
        finally:
            conn.close()

    def get_user_role(self, project_id: str, user_id: str) -> str | None:
        """Get a user's role in a project."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT role FROM project_member WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            return row["role"] if row else None
        finally:
            conn.close()

    def list_user_projects(self, user_id: str) -> list[dict]:
        """List all projects a user is a member of."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT pm.project_id, pm.role, p.name as project_name, p.status "
                "FROM project_member pm JOIN project p ON pm.project_id = p.id "
                "WHERE pm.user_id = ?",
                (user_id,),
            ).fetchall()
            return [
                {
                    "project_id": r["project_id"],
                    "role": r["role"],
                    "project_name": r["project_name"],
                    "status": r["status"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_member(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "user_id": row["user_id"],
            "username": row["username"] if "username" in row.keys() else "",
            "display_name": row["display_name"] if "display_name" in row.keys() else "",
            "role": row["role"],
            "joined_at": row["joined_at"],
        }
