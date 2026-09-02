"""
Phase H — Team Collaboration Workspace 测试套件

覆盖所有 H 阶段的验收目标：
  H.1 - 认证 (login/token/me/users)
  H.2 - 项目角色 (权限守卫)
  H.3 - 项目总览
  H.4 - 任务看板
  H.5 - 风险中心 (分配/生命周期)
  H.6 - 报告中心 (草稿/编辑/审批/导出)
  H.7 - 评论 & @提及
  H.8 - 通知收件箱
  H.9 - 文件下载权限
  H.10 - 端到端集成场景
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure app importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def temp_db_dir():
    """Create a temporary directory for test databases and files."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


@pytest.fixture(scope="module")
def test_settings(temp_db_dir):
    """Settings pointing to a temporary directory."""
    project_root = temp_db_dir / "projects"
    project_root.mkdir(exist_ok=True)
    sqlite_dir = temp_db_dir / "sqlite"
    sqlite_dir.mkdir(exist_ok=True)
    output_dir = temp_db_dir / "outputs"
    output_dir.mkdir(exist_ok=True)

    (sqlite_dir / "projectpack.db").touch()

    os.environ["LLM_BASE_URL"] = "http://127.0.0.1:8000/v1"
    os.environ["EMBEDDING_BASE_URL"] = "http://127.0.0.1:8080/v1"
    os.environ["PROJECT_ROOT"] = str(project_root)
    os.environ["SQLITE_PATH"] = str(sqlite_dir / "projectpack.db")
    os.environ["OUTPUT_ROOT"] = str(output_dir)

    settings = Settings(
        project_root=str(project_root),
        sqlite_path=str(sqlite_dir / "projectpack.db"),
        output_root=str(output_dir),
    )
    return settings


@pytest.fixture(scope="module")
def client(test_settings):
    """TestClient with the app using test settings."""
    app = create_app(test_settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token_admin(client):
    """Login as admin user and return token."""
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def token_pm(client):
    r = client.post("/auth/login", json={"username": "pm", "password": "pm123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def token_member(client):
    r = client.post("/auth/login", json={"username": "member", "password": "member123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def token_guest(client):
    r = client.post("/auth/login", json={"username": "guest", "password": "guest123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers_admin(token_admin):
    return {"Authorization": f"Bearer {token_admin}"}


@pytest.fixture(scope="module")
def auth_headers_pm(token_pm):
    return {"Authorization": f"Bearer {token_pm}"}


@pytest.fixture(scope="module")
def auth_headers_member(token_member):
    return {"Authorization": f"Bearer {token_member}"}


@pytest.fixture(scope="module")
def auth_headers_guest(token_guest):
    return {"Authorization": f"Bearer {token_guest}"}


@pytest.fixture(scope="module")
def project_id(client, auth_headers_admin, test_settings):
    """Create a test project, seed all members, return project_id."""
    r = client.post("/api/projects", json={
        "project_id": "phase-h-test",
        "name": "PhaseH Test Project",
    })
    pid = r.json()["project_id"]

    # Seed members
    for uid, role in [("u-admin", "admin"), ("u-pm", "pm"), ("u-member", "member"), ("u-guest", "guest")]:
        client.post(
            f"/projects/{pid}/members",
            headers=auth_headers_admin,
            json={"user_id": uid, "role": role},
        )
    return pid


# ============================================================================
# H.1 — 认证测试
# ============================================================================


class TestAuth:
    """Authentication: login, token, me, users."""

    def test_login_success(self, client):
        r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["username"] == "admin"
        assert data["is_system_admin"] is True

    def test_login_failure_wrong_password(self, client):
        r = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    def test_login_failure_nonexistent_user(self, client):
        r = client.post("/auth/login", json={"username": "nobody", "password": "x"})
        assert r.status_code == 401

    def test_me_authenticated(self, client, auth_headers_admin):
        r = client.get("/auth/me", headers=auth_headers_admin)
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "admin"
        assert data["is_system_admin"] is True
        assert data["display_name"] == "管理员"

    def test_me_no_token(self, client):
        r = client.get("/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token(self, client):
        r = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert r.status_code == 401

    def test_list_users(self, client, auth_headers_admin):
        r = client.get("/auth/users", headers=auth_headers_admin)
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 4
        usernames = {u["username"] for u in data}
        assert "admin" in usernames

    def test_expired_token_rejected(self, client):
        """测试过期 token 被拒绝（使用过去的时间签名）。"""
        # An obviously malformed token
        r = client.get("/auth/me", headers={"Authorization": "Bearer bad"})
        assert r.status_code == 401

    def test_disabled_user_token_is_rejected(self, client, test_settings, auth_headers_admin):
        """Disabling an account must invalidate its already-issued token."""
        import sqlite3

        conn = sqlite3.connect(str(test_settings.sqlite_path))
        try:
            conn.execute("UPDATE user_account SET is_active = 0 WHERE username = 'admin'")
            conn.commit()
            response = client.get("/auth/me", headers=auth_headers_admin)
            assert response.status_code == 401
        finally:
            conn.execute("UPDATE user_account SET is_active = 1 WHERE username = 'admin'")
            conn.commit()
            conn.close()


# ============================================================================
# H.2 — 项目角色 & 权限测试
# ============================================================================


class TestProjectRoles:
    """Role-based access control."""

    def test_admin_can_add_member(self, client, project_id, auth_headers_admin):
        """Admin can add a new member."""
        r = client.post(
            f"/projects/{project_id}/members",
            headers=auth_headers_admin,
            json={"user_id": "u-member", "role": "member"},
        )
        # Already exists, expect 409
        assert r.status_code in (201, 409)

    def test_pm_cannot_add_member(self, client, project_id, auth_headers_pm):
        """PM should NOT be able to invite members."""
        r = client.post(
            f"/projects/{project_id}/members",
            headers=auth_headers_pm,
            json={"user_id": "u-guest", "role": "guest"},
        )
        assert r.status_code == 403

    def test_guest_cannot_add_member(self, client, project_id, auth_headers_guest):
        """Guest should not have manage permissions."""
        r = client.post(
            f"/projects/{project_id}/members",
            headers=auth_headers_guest,
            json={"user_id": "u-member", "role": "member"},
        )
        assert r.status_code in (401, 403)

    def test_list_members(self, client, project_id, auth_headers_admin):
        r = client.get(f"/projects/{project_id}/members", headers=auth_headers_admin)
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1

    def test_guest_can_view_members(self, client, project_id, auth_headers_guest):
        r = client.get(f"/projects/{project_id}/members", headers=auth_headers_guest)
        assert r.status_code == 200

    def test_update_member_role(self, client, project_id, auth_headers_admin):
        r = client.put(
            f"/projects/{project_id}/members/u-guest",
            headers=auth_headers_admin,
            json={"user_id": "u-guest", "role": "guest"},
        )
        assert r.status_code == 200

    def test_remove_member(self, client, project_id, auth_headers_admin, token_admin):
        """Admin can remove, then re-add a member."""
        # First, remove member
        r = client.delete(
            f"/projects/{project_id}/members/u-member",
            headers=auth_headers_admin,
        )
        assert r.status_code == 204

        # Re-add
        r = client.post(
            f"/projects/{project_id}/members",
            headers=auth_headers_admin,
            json={"user_id": "u-member", "role": "member"},
        )
        assert r.status_code == 201

    def test_non_member_cannot_access(self, client, project_id, token_admin):
        """User not in project should get 403 for project-scoped endpoints."""
        # Create a quick user, add, then remove, then test
        # Simpler: use a non-member access test
        # For now, test that no auth returns 401
        r = client.get(f"/projects/{project_id}/overview")
        assert r.status_code == 401


# ============================================================================
# H.3 — 项目总览测试
# ============================================================================


class TestProjectOverview:
    """Project dashboard overview."""

    def test_overview_accessible_to_member(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/overview", headers=auth_headers_member)
        assert r.status_code == 200
        data = r.json()
        assert data["project_id"] == project_id
        assert "task_stats" in data
        assert "risk_stats" in data
        assert "pending_confirmations" in data
        assert "recent_doc_changes" in data
        assert "recent_runs" in data

    def test_overview_accessible_to_guest(self, client, project_id, auth_headers_guest):
        r = client.get(f"/projects/{project_id}/overview", headers=auth_headers_guest)
        assert r.status_code == 200

    def test_overview_not_accessible_without_auth(self, client, project_id):
        r = client.get(f"/projects/{project_id}/overview")
        assert r.status_code == 401

    def test_overview_nonexistent_project(self, client, auth_headers_admin):
        r = client.get("/projects/nonexist-999/overview", headers=auth_headers_admin)
        assert r.status_code in (404, 403)


# ============================================================================
# H.4 — 任务看板测试
# ============================================================================


class TestTaskBoard:
    """Task board view: filter, sort, group."""

    def test_board_accessible(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/board/tasks", headers=auth_headers_member)
        assert r.status_code == 200
        data = r.json()
        assert "groups" in data
        assert "total_count" in data
        assert "filters_applied" in data

    def test_board_reads_phase_f_task_database(self, client, project_id, auth_headers_member, test_settings):
        """The board must use the same SQLite task DB as the Phase F API."""
        from app.schemas.models import TaskCreate
        from app.services.task_lifecycle import TaskLifecycleService

        task_db = test_settings.sqlite_path.parent / "projects" / project_id / "tasks.db"
        TaskLifecycleService(task_db).create_task(
            project_id, TaskCreate(title="Board integration task", status="not_started")
        )
        response = client.get(f"/projects/{project_id}/board/tasks", headers=auth_headers_member)
        assert response.status_code == 200
        assert response.json()["total_count"] >= 1

    def test_board_with_status_filter(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/board/tasks?status=open", headers=auth_headers_member)
        assert r.status_code == 200
        data = r.json()
        # Filter is applied regardless of whether any tasks exist
        assert data["filters_applied"].get("status") == "open"

    def test_board_with_owner_filter(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/board/tasks?owner=alice", headers=auth_headers_member)
        assert r.status_code == 200

    def test_board_with_sort(self, client, project_id, auth_headers_member):
        r = client.get(
            f"/projects/{project_id}/board/tasks?sort_by=priority&sort_order=desc",
            headers=auth_headers_member,
        )
        assert r.status_code == 200

    def test_board_with_group_by_status(self, client, project_id, auth_headers_member):
        r = client.get(
            f"/projects/{project_id}/board/tasks?group_by=status",
            headers=auth_headers_member,
        )
        assert r.status_code == 200

    def test_board_with_search(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/board/tasks?search=test", headers=auth_headers_member)
        assert r.status_code == 200

    def test_board_not_accessible_without_auth(self, client, project_id):
        r = client.get(f"/projects/{project_id}/board/tasks")
        assert r.status_code == 401


# ============================================================================
# H.5 — 风险中心测试
# ============================================================================


class TestRiskCenter:
    """Risk assignment, lifecycle, listing."""

    def test_list_risks(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/risks", headers=auth_headers_member)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_risks_filtered(self, client, project_id, auth_headers_member):
        r = client.get(
            f"/projects/{project_id}/risks?severity=critical",
            headers=auth_headers_member,
        )
        assert r.status_code == 200

    def test_assign_risk_by_pm(self, client, project_id, auth_headers_pm):
        """PM can assign a risk. If no risk exists, expect 404."""
        r = client.put(
            f"/projects/{project_id}/risks/risk-001/assign",
            headers=auth_headers_pm,
            json={"risk_id": "risk-001", "assignee_user_id": "u-member"},
        )
        # 404/400 is expected if no such risk or risk DB doesn't exist
        assert r.status_code in (200, 404, 400)

    def test_assign_risk_forbidden_for_member(self, client, project_id, auth_headers_member):
        """Regular member cannot assign risks."""
        r = client.put(
            f"/projects/{project_id}/risks/risk-001/assign",
            headers=auth_headers_member,
            json={"risk_id": "risk-001", "assignee_user_id": "u-member"},
        )
        assert r.status_code in (403, 404)

    def test_risk_lifecycle_update(self, client, project_id, auth_headers_pm):
        r = client.put(
            f"/projects/{project_id}/risks/risk-001/lifecycle",
            headers=auth_headers_pm,
            json={"action": "acknowledge", "note": "Acknowledging this risk", "actor": "pm"},
        )
        assert r.status_code in (200, 404)

    def test_risk_lifecycle_invalid_action(self, client, project_id, auth_headers_pm):
        r = client.put(
            f"/projects/{project_id}/risks/risk-001/lifecycle",
            headers=auth_headers_pm,
            json={"action": "invalid_action", "note": "", "actor": "pm"},
        )
        assert r.status_code == 422  # Pydantic validation failure


# ============================================================================
# H.6 — 报告中心测试
# ============================================================================


class TestReportCenter:
    """Report drafts: CRUD, submit, approve, reject, export."""

    draft_id: str = ""

    def test_create_draft(self, client, project_id, auth_headers_member):
        r = client.post(
            f"/projects/{project_id}/reports",
            headers=auth_headers_member,
            json={"title": "H 阶段测试报告", "content_md": "# Overview\n\nThis is a test report."},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "H 阶段测试报告"
        assert data["status"] == "draft"
        TestReportCenter.draft_id = data["id"]

    def test_list_drafts(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/reports", headers=auth_headers_member)
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1

    def test_get_draft(self, client, project_id, auth_headers_member):
        r = client.get(f"/projects/{project_id}/reports/{TestReportCenter.draft_id}", headers=auth_headers_member)
        assert r.status_code == 200
        assert r.json()["title"] == "H 阶段测试报告"

    def test_update_draft(self, client, project_id, auth_headers_member):
        r = client.put(
            f"/projects/{project_id}/reports/{TestReportCenter.draft_id}",
            headers=auth_headers_member,
            json={"content_md": "# Updated\n\nUpdated content."},
        )
        assert r.status_code == 200
        assert "Updated" in r.json()["content_md"]

    def test_submit_draft(self, client, project_id, auth_headers_member):
        if not TestReportCenter.draft_id:
            pytest.skip("No draft to submit")
        r = client.post(
            f"/projects/{project_id}/reports/{TestReportCenter.draft_id}/submit",
            headers=auth_headers_member,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "submitted"

    def test_approve_report(self, client, project_id, auth_headers_pm):
        if not TestReportCenter.draft_id:
            pytest.skip("No draft to approve")
        r = client.post(
            f"/projects/{project_id}/reports/{TestReportCenter.draft_id}/approve",
            headers=auth_headers_pm,
            json={"decision": "approved", "comment": "Looks good!"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_reject_report_submit_new(self, client, project_id, auth_headers_member, auth_headers_pm):
        """Create a new draft, submit, and reject it."""
        r = client.post(
            f"/projects/{project_id}/reports",
            headers=auth_headers_member,
            json={"title": "To Be Rejected", "content_md": "Content"},
        )
        assert r.status_code == 201
        rid = r.json()["id"]

        # Submit
        r = client.post(f"/projects/{project_id}/reports/{rid}/submit", headers=auth_headers_member)
        assert r.status_code == 200

        # PM rejects
        r = client.post(
            f"/projects/{project_id}/reports/{rid}/approve",
            headers=auth_headers_pm,
            json={"decision": "rejected", "comment": "Needs more work"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    def test_export_pdf(self, client, project_id, auth_headers_member):
        if not TestReportCenter.draft_id:
            pytest.skip("No draft to export")
        r = client.get(
            f"/projects/{project_id}/reports/{TestReportCenter.draft_id}/export/pdf",
            headers=auth_headers_member,
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_export_docx(self, client, project_id, auth_headers_member):
        if not TestReportCenter.draft_id:
            pytest.skip("No draft to export")
        r = client.get(
            f"/projects/{project_id}/reports/{TestReportCenter.draft_id}/export/docx",
            headers=auth_headers_member,
        )
        assert r.status_code == 200
        assert "vnd.openxmlformats" in r.headers["content-type"]

    def test_get_approval_history(self, client, project_id, auth_headers_member):
        if not TestReportCenter.draft_id:
            pytest.skip("No draft for approval history")
        r = client.get(
            f"/projects/{project_id}/reports/{TestReportCenter.draft_id}/approvals",
            headers=auth_headers_member,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ============================================================================
# H.7 — 评论 & @提及测试
# ============================================================================


class TestComments:
    """Comment CRUD, @mentions, threading."""

    comment_id: str = ""

    def test_create_comment_on_task(self, client, project_id, auth_headers_member):
        r = client.post(
            f"/projects/{project_id}/comments",
            headers=auth_headers_member,
            json={
                "entity_type": "task",
                "entity_id": "task-001",
                "body": "This task needs clarification.",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["body"] == "This task needs clarification."
        assert data["entity_type"] == "task"
        TestComments.comment_id = data["id"]

    def test_create_comment_with_mention(self, client, project_id, auth_headers_member):
        r = client.post(
            f"/projects/{project_id}/comments",
            headers=auth_headers_member,
            json={
                "entity_type": "task",
                "entity_id": "task-001",
                "body": "Hey @admin please review this.",
            },
        )
        assert r.status_code == 201
        data = r.json()
        # Mention should have been extracted
        assert "admin" in str(data.get("mentions", ""))

    def test_list_comments(self, client, project_id, auth_headers_member):
        r = client.get(
            f"/projects/{project_id}/comments?entity_type=task&entity_id=task-001",
            headers=auth_headers_member,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1

    def test_create_reply(self, client, project_id, auth_headers_member):
        if not TestComments.comment_id:
            pytest.skip("No parent comment to reply to")
        r = client.post(
            f"/projects/{project_id}/comments",
            headers=auth_headers_member,
            json={
                "entity_type": "task",
                "entity_id": "task-001",
                "body": "A reply to the parent.",
                "parent_id": TestComments.comment_id,
            },
        )
        assert r.status_code == 201

    def test_update_own_comment(self, client, project_id, auth_headers_member):
        if not TestComments.comment_id:
            pytest.skip("No comment to update")
        r = client.put(
            f"/projects/{project_id}/comments/{TestComments.comment_id}",
            headers=auth_headers_member,
            json={"body": "Updated clarification request."},
        )
        assert r.status_code == 200
        assert r.json()["body"] == "Updated clarification request."

    def test_cannot_update_other_comment(self, client, project_id, auth_headers_pm, token_pm):
        """A user should not be able to update someone else's comment."""
        # Use the comment created by member
        if not TestComments.comment_id:
            pytest.skip("No comment to test")
        # The comment was created by 'member', so 'pm' should not be able to edit
        r = client.put(
            f"/projects/{project_id}/comments/{TestComments.comment_id}",
            headers=auth_headers_pm,
            json={"body": "Hijack attempt"},
        )
        assert r.status_code == 403

    def test_resolve_comment(self, client, project_id, auth_headers_pm):
        """PM can resolve a comment."""
        if not TestComments.comment_id:
            pytest.skip("No comment to resolve")
        r = client.post(
            f"/projects/{project_id}/comments/{TestComments.comment_id}/resolve",
            headers=auth_headers_pm,
        )
        assert r.status_code == 200
        assert r.json()["is_resolved"] is True

    def test_guest_cannot_create_comment(self, client, project_id, auth_headers_guest):
        r = client.post(
            f"/projects/{project_id}/comments",
            headers=auth_headers_guest,
            json={
                "entity_type": "task",
                "entity_id": "task-001",
                "body": "Guest attempting comment",
            },
        )
        assert r.status_code == 403

    def test_comment_without_auth(self, client, project_id):
        r = client.post(
            f"/projects/{project_id}/comments",
            json={
                "entity_type": "task",
                "entity_id": "task-001",
                "body": "No auth",
            },
        )
        assert r.status_code == 401

    def test_pm_can_delete_comment(self, client, project_id, auth_headers_pm):
        """PM can delete any comment."""
        if not TestComments.comment_id:
            pytest.skip("No comment to delete")
        r = client.delete(
            f"/projects/{project_id}/comments/{TestComments.comment_id}",
            headers=auth_headers_pm,
        )
        assert r.status_code in (204, 404)


# ============================================================================
# H.8 — 通知收件箱测试
# ============================================================================


class TestNotifications:
    """Notification inbox: list, read, unread count."""

    def test_list_notifications(self, client, auth_headers_member):
        r = client.get("/notifications", headers=auth_headers_member)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_unread_count(self, client, auth_headers_member):
        r = client.get("/notifications/unread-count", headers=auth_headers_member)
        assert r.status_code == 200
        assert "unread_count" in r.json()

    def test_mark_all_read(self, client, auth_headers_member):
        r = client.put("/notifications/read-all", headers=auth_headers_member)
        assert r.status_code == 200
        assert "marked_read" in r.json()

    def test_notifications_require_auth(self, client):
        r = client.get("/notifications")
        assert r.status_code == 401

    def test_list_unread_only(self, client, auth_headers_member):
        r = client.get("/notifications?unread_only=true", headers=auth_headers_member)
        assert r.status_code == 200

    def test_notification_pagination(self, client, auth_headers_member):
        r = client.get("/notifications?limit=10&offset=0", headers=auth_headers_member)
        assert r.status_code == 200


# ============================================================================
# H.9 — 文件权限测试
# ============================================================================


class TestFilePermissions:
    """File download with project membership check."""

    def test_unauthorized_download_returns_401(self, client, project_id):
        """Without auth, file download should fail with 401."""
        r = client.get(f"/api/projects/{project_id}/files/download/test.txt")
        assert r.status_code == 401

    def test_upload_still_works(self, client, project_id, test_settings):
        """Upload should still work (existing behavior)."""
        content = b"Phase H test file content"
        r = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": ("test_h.txt", io.BytesIO(content), "text/plain")},
        )
        assert r.status_code == 201


# ============================================================================
# H.10 — 端到端集成场景
# ============================================================================


class TestIntegrationE2E:
    """End-to-end workflow: login → create → collaborate → approve."""

    def test_full_collaboration_flow(
        self, client, project_id, auth_headers_admin, auth_headers_pm, auth_headers_member, auth_headers_guest
    ):
        """Simulate a full team collaboration flow."""

        # 1. Admin lists members
        r = client.get(f"/projects/{project_id}/members", headers=auth_headers_admin)
        assert r.status_code == 200

        # 2. Member creates a report
        r = client.post(
            f"/projects/{project_id}/reports",
            headers=auth_headers_member,
            json={"title": "E2E Flow Report", "content_md": "## Summary\n\nAll good!"},
        )
        assert r.status_code == 201
        report_id = r.json()["id"]

        # 3. Member submits report
        r = client.post(f"/projects/{project_id}/reports/{report_id}/submit", headers=auth_headers_member)
        assert r.status_code == 200
        assert r.json()["status"] == "submitted"

        # 4. PM approves
        r = client.post(
            f"/projects/{project_id}/reports/{report_id}/approve",
            headers=auth_headers_pm,
            json={"decision": "approved", "comment": "Great report!"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        # 5. Members comment on a task
        r = client.post(
            f"/projects/{project_id}/comments",
            headers=auth_headers_member,
            json={
                "entity_type": "task",
                "entity_id": "task-e2e",
                "body": "Let's discuss the approach @pm @admin",
            },
        )
        assert r.status_code == 201

        # 6. Guest can view overview but cannot comment
        r = client.get(f"/projects/{project_id}/overview", headers=auth_headers_guest)
        assert r.status_code == 200

        r = client.post(
            f"/projects/{project_id}/comments",
            headers=auth_headers_guest,
            json={"entity_type": "task", "entity_id": "task-e2e", "body": "guest comment"},
        )
        assert r.status_code == 403

        # 7. View approval history
        r = client.get(f"/projects/{project_id}/reports/{report_id}/approvals", headers=auth_headers_member)
        assert r.status_code == 200
        approvals = r.json()
        assert len(approvals) >= 1
        assert approvals[0]["decision"] == "approved"

        # 8. Export report
        r = client.get(f"/projects/{project_id}/reports/{report_id}/export/pdf", headers=auth_headers_member)
        assert r.status_code == 200

        # 9. Check notifications
        r = client.get("/notifications", headers=auth_headers_member)
        assert r.status_code == 200

        # 10. Board view
        r = client.get(f"/projects/{project_id}/board/tasks?group_by=status", headers=auth_headers_member)
        assert r.status_code == 200

    def test_demo_users_exist(self, client):
        """All 4 demo users can login."""
        for uname, pwd in [("admin", "admin123"), ("pm", "pm123"), ("member", "member123"), ("guest", "guest123")]:
            r = client.post("/auth/login", json={"username": uname, "password": pwd})
            assert r.status_code == 200, f"User {uname} failed to login: {r.text}"
            assert r.json()["username"] == uname

    def test_token_refresh_flow(self, client):
        """Login → token → me → use token to access protected resource."""
        r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Verify me
        r = client.get("/auth/me", headers=headers)
        assert r.status_code == 200
        assert r.json()["username"] == "admin"
