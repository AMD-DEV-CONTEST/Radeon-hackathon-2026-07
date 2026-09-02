"""Stage I — Automation tasks and token manager tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.automation_tasks import AutomationTaskService, AutomationTaskStatus
from app.services.token_manager import TokenManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


def _setup_project(client: TestClient) -> None:
    assert client.post(
        "/api/projects", json={"project_id": "demo-project", "name": "Demo"}
    ).status_code == 201
    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    user_id = client.get("/auth/me").json()["user_id"]
    assert client.post(
        "/projects/demo-project/members", json={"user_id": user_id, "role": "admin"}
    ).status_code == 201


# ---------------------------------------------------------------------------
# Automation Task Service — Unit Tests
# ---------------------------------------------------------------------------


def test_automation_task_create_and_get(tmp_path: Path) -> None:
    """Create automation task and retrieve it."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto.db"))
    task = svc.create("proj-1", "Nightly Report", "on_schedule",
                      {"schedule": "0 2 * * *", "report_type": "summary"})
    assert task.id.startswith("auto_")
    assert task.name == "Nightly Report"
    assert task.type == "on_schedule"
    assert task.status == AutomationTaskStatus.ACTIVE.value
    assert task.project_id == "proj-1"


def test_automation_task_list_by_project(tmp_path: Path) -> None:
    """List automation tasks filtered by project."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_list.db"))
    svc.create("p1", "Task A")
    svc.create("p1", "Task B")
    svc.create("p2", "Task C")

    p1_tasks = svc.list_by_project("p1")
    assert len(p1_tasks) == 2
    assert all(t.project_id == "p1" for t in p1_tasks)

    p2_tasks = svc.list_by_project("p2")
    assert len(p2_tasks) == 1


def test_automation_task_pause_and_resume(tmp_path: Path) -> None:
    """Pause and resume an automation task."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_pause.db"))
    task = svc.create("p1", "Pausable Task")

    # Pause
    paused = svc.pause(task.id)
    assert paused.status == AutomationTaskStatus.PAUSED.value

    # Resume
    resumed = svc.resume(task.id)
    assert resumed.status == AutomationTaskStatus.ACTIVE.value


def test_automation_task_cannot_pause_twice(tmp_path: Path) -> None:
    """Pausing an already paused task raises ValueError."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_dbl_pause.db"))
    task = svc.create("p1", "T1")
    svc.pause(task.id)
    with pytest.raises(ValueError, match="already paused"):
        svc.pause(task.id)


def test_automation_task_cannot_resume_active(tmp_path: Path) -> None:
    """Resuming an already active task raises ValueError."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_dbl_resume.db"))
    task = svc.create("p1", "T1")
    with pytest.raises(ValueError, match="already active"):
        svc.resume(task.id)


def test_automation_task_delete_cancels(tmp_path: Path) -> None:
    """Delete (soft) sets status to cancelled."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_delete.db"))
    task = svc.create("p1", "Deletable")
    result = svc.delete(task.id)
    assert result is True

    deleted = svc.get(task.id)
    assert deleted.status == AutomationTaskStatus.CANCELLED.value


def test_automation_task_cannot_resume_cancelled(tmp_path: Path) -> None:
    """Cannot resume a cancelled task."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_cancelled.db"))
    task = svc.create("p1", "T1")
    svc.delete(task.id)
    with pytest.raises(ValueError, match="cancelled"):
        svc.resume(task.id)


def test_automation_task_cannot_pause_cancelled(tmp_path: Path) -> None:
    """Cannot pause a cancelled task."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_cp.db"))
    task = svc.create("p1", "T1")
    svc.delete(task.id)
    with pytest.raises(ValueError, match="cancelled"):
        svc.pause(task.id)


def test_automation_task_get_missing_raises(tmp_path: Path) -> None:
    """Get non-existent task raises KeyError."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_missing.db"))
    with pytest.raises(KeyError):
        svc.get("auto_nonexistent")


def test_automation_task_dry_run(tmp_path: Path) -> None:
    """Dry run simulates without side effects."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_dry.db"))
    task = svc.create("p1", "Dry Run Task", config={"action": "send_report"})
    result = svc.dry_run(task.id)
    assert result["run_type"] == "dry_run"
    assert result["task_id"] == task.id
    assert "simulated_actions" in result

    # Verify task is still active
    t = svc.get(task.id)
    assert t.status == AutomationTaskStatus.ACTIVE.value


def test_automation_task_audit_log(tmp_path: Path) -> None:
    """Audit log captures create/pause/resume/dry-run events."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_audit.db"))
    task = svc.create("p1", "Audited Task")
    svc.pause(task.id)
    svc.resume(task.id)
    svc.dry_run(task.id)

    log = svc.audit_log(task.id)
    assert len(log) >= 4
    actions = [e["action"] for e in log]
    assert "created" in actions
    assert "paused" in actions
    assert "resumed" in actions
    assert "dry_run" in actions


def test_automation_task_list_runs(tmp_path: Path) -> None:
    """List task runs after dry-run."""
    svc = AutomationTaskService(db_path=str(tmp_path / "auto_runs.db"))
    task = svc.create("p1", "Runnable")
    svc.dry_run(task.id)
    runs = svc.list_runs(task.id)
    assert len(runs) >= 1


# ---------------------------------------------------------------------------
# Automation Task API — Integration Tests
# ---------------------------------------------------------------------------


def test_api_automation_task_requires_authentication(tmp_path: Path) -> None:
    """Automation task APIs do not expose project data to anonymous callers."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/projects/demo-project/automation-tasks").status_code == 401


def test_api_create_automation_task(tmp_path: Path) -> None:
    """POST /api/automation-tasks creates a task."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        resp = client.post("/api/automation-tasks", json={
            "project_id": "demo-project",
            "name": "API Created Task",
            "type": "on_demand",
            "config": {"key": "value"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["task"]["name"] == "API Created Task"
        assert data["task"]["status"] == "active"


def test_api_list_automation_tasks(tmp_path: Path) -> None:
    """GET /api/projects/{id}/automation-tasks returns tasks."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        client.post("/api/automation-tasks", json={
            "project_id": "demo-project", "name": "Task 1",
        })
        client.post("/api/automation-tasks", json={
            "project_id": "demo-project", "name": "Task 2",
        })

        resp = client.get("/api/projects/demo-project/automation-tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["count"] == 2


def test_api_pause_resume_automation_task(tmp_path: Path) -> None:
    """POST /api/automation-tasks/{id}/pause and /resume."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/automation-tasks", json={
            "project_id": "demo-project", "name": "Pausable",
        }).json()
        task_id = created["task"]["id"]

        # Pause
        resp = client.post(f"/api/automation-tasks/{task_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["task"]["status"] == "paused"

        # Resume
        resp = client.post(f"/api/automation-tasks/{task_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["task"]["status"] == "active"


def test_api_pause_already_paused_returns_409(tmp_path: Path) -> None:
    """Pausing paused task returns 409."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/automation-tasks", json={
            "project_id": "demo-project", "name": "Double Pause",
        }).json()
        task_id = created["task"]["id"]
        client.post(f"/api/automation-tasks/{task_id}/pause")
        resp = client.post(f"/api/automation-tasks/{task_id}/pause")
        assert resp.status_code == 409


def test_api_dry_run_automation_task(tmp_path: Path) -> None:
    """POST /api/automation-tasks/{id}/dry-run simulates."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/automation-tasks", json={
            "project_id": "demo-project", "name": "Dry Runner",
        }).json()
        task_id = created["task"]["id"]

        resp = client.post(f"/api/automation-tasks/{task_id}/dry-run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"]["run_type"] == "dry_run"


def test_api_delete_automation_task(tmp_path: Path) -> None:
    """POST /api/automation-tasks/{id}/delete cancels."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/automation-tasks", json={
            "project_id": "demo-project", "name": "Deletable",
        }).json()
        task_id = created["task"]["id"]

        resp = client.post(f"/api/automation-tasks/{task_id}/delete")
        assert resp.status_code == 200
        assert "cancelled" in resp.json()["message"].lower()


def test_api_audit_automation_task(tmp_path: Path) -> None:
    """GET /api/automation-tasks/{id}/audit returns audit log."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        created = client.post("/api/automation-tasks", json={
            "project_id": "demo-project", "name": "Auditable",
        }).json()
        task_id = created["task"]["id"]
        client.post(f"/api/automation-tasks/{task_id}/pause")
        client.post(f"/api/automation-tasks/{task_id}/resume")

        resp = client.get(f"/api/automation-tasks/{task_id}/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 3  # create, pause, resume


def test_api_create_automation_task_validation(tmp_path: Path) -> None:
    """Creating task without project_id or name returns 400."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        resp = client.post("/api/automation-tasks", json={"name": "No Project"})
        assert resp.status_code == 400

        resp = client.post("/api/automation-tasks", json={"project_id": "demo-project"})
        assert resp.status_code == 400


def test_api_missing_automation_task_404(tmp_path: Path) -> None:
    """Operations on non-existent automation task return 404."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        resp = client.post("/api/automation-tasks/auto_bogus/pause")
        assert resp.status_code == 404

        resp = client.post("/api/automation-tasks/auto_bogus/resume")
        assert resp.status_code == 404

        resp = client.post("/api/automation-tasks/auto_bogus/dry-run")
        assert resp.status_code == 404

        resp = client.post("/api/automation-tasks/auto_bogus/delete")
        assert resp.status_code == 404

        resp = client.get("/api/automation-tasks/auto_bogus/audit")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Token Manager
# ---------------------------------------------------------------------------


def test_token_manager_store_and_retrieve(tmp_path: Path) -> None:
    """Store a token and retrieve it decrypted."""
    tm = TokenManager(db_path=str(tmp_path / "tok.db"), secret="my-secret-key-32bytes!")
    token_id = tm.store(service="github", token_value="ghp_s3cr3t_t0k3n",
                        project_id="p1", label="GitHub PAT")
    assert token_id.startswith("tok_")

    retrieved = tm.retrieve(token_id)
    assert retrieved == "ghp_s3cr3t_t0k3n"


def test_token_manager_list_never_exposes_value(tmp_path: Path) -> None:
    """Listing tokens returns metadata without the encrypted value."""
    tm = TokenManager(db_path=str(tmp_path / "tok_list.db"), secret="k" * 32)
    tm.store("github", "secret1", project_id="p1", label="GitHub")
    tm.store("jira", "secret2", project_id="p1", label="JIRA")

    tokens = tm.list_tokens(project_id="p1")
    assert len(tokens) == 2
    for t in tokens:
        assert "id" in t
        assert "service" in t
        assert "label" in t
        assert "encrypted_value" not in t
        assert "value" not in t
        assert "token" not in t


def test_token_manager_retrieve_missing_returns_none(tmp_path: Path) -> None:
    """Retrieving a missing token returns None."""
    tm = TokenManager(db_path=str(tmp_path / "tok_miss.db"), secret="s")
    assert tm.retrieve("tok_nonexistent") is None


def test_token_manager_delete(tmp_path: Path) -> None:
    """Delete removes a token permanently."""
    tm = TokenManager(db_path=str(tmp_path / "tok_del.db"), secret="x" * 32)
    tid = tm.store("ci", "ci-token")
    assert tm.delete(tid) is True
    assert tm.retrieve(tid) is None
    assert tm.delete(tid) is False  # already gone


def test_token_manager_list_by_service(tmp_path: Path) -> None:
    """Filter tokens by service name."""
    tm = TokenManager(db_path=str(tmp_path / "tok_svc.db"), secret="k" * 32)
    tm.store("github", "t1", project_id="p1")
    tm.store("jira", "t2", project_id="p1")

    github_tokens = tm.list_tokens(service="github")
    assert len(github_tokens) == 1
    assert github_tokens[0]["service"] == "github"


def test_token_manager_list_by_service_and_project(tmp_path: Path) -> None:
    """Filter tokens by service and project."""
    tm = TokenManager(db_path=str(tmp_path / "tok_sp.db"), secret="k" * 32)
    tm.store("github", "t1", project_id="p1")
    tm.store("github", "t2", project_id="p2")

    results = tm.list_tokens(service="github", project_id="p1")
    assert len(results) == 1
    assert results[0]["project_id"] == "p1"


def test_token_manager_sanitize_for_log(tmp_path: Path) -> None:
    """sanitize_for_log redacts token values."""
    tm = TokenManager(db_path=str(tmp_path / "tok_san.db"), secret="a" * 32)
    assert tm.sanitize_for_log("ghp_abcdefghijklmnop") == "ghp_****mnop"
    assert tm.sanitize_for_log("ab") == "****"
    assert tm.sanitize_for_log("") == ""
