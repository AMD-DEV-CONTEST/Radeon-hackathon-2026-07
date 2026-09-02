from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        enforce_project_authorization=True,
    )


def _token(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _task_body(status: str = "not_started") -> dict[str, object]:
    return {"title": "Secure task", "status": status, "acceptance_criteria": "Verified"}


def test_task_routes_require_membership_and_server_owned_audit_actor(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        admin = _token(client, "admin", "admin123")
        guest = _token(client, "guest", "guest123")
        assert client.post(
            "/api/projects", headers=admin,
            json={"project_id": "secure-tasks", "name": "Secure tasks"},
        ).status_code == 201

        assert client.get("/api/projects/secure-tasks/tasks").status_code == 401
        assert client.get("/api/projects/secure-tasks/tasks", headers=guest).status_code == 403
        created = client.post("/api/projects/secure-tasks/tasks", headers=admin, json=_task_body())
        assert created.status_code == 201
        task_id = created.json()["id"]

        # Browser supplied actor values must be ignored in favour of the JWT user.
        transition = client.post(
            f"/api/projects/secure-tasks/tasks/{task_id}/transition",
            headers=admin,
            json={"status": "in_progress", "reason": "Start work", "changed_by": "forged-user"},
        )
        assert transition.status_code == 200
        history = client.get(f"/api/projects/secure-tasks/tasks/{task_id}/history", headers=admin)
        assert history.status_code == 200
        assert history.json()[-1]["changed_by"] == "admin"

        # Guest may be granted view access, but cannot mutate task state.
        app.state.membership_service.add_member("secure-tasks", "u-guest", "guest")
        assert client.get("/api/projects/secure-tasks/tasks", headers=guest).status_code == 200
        denied = client.post(
            f"/api/projects/secure-tasks/tasks/{task_id}/transition",
            headers=guest,
            json={"status": "completed", "reason": "forbidden"},
        )
        assert denied.status_code == 403


def test_confirmation_and_import_ignore_forged_actor_fields(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        admin = _token(client, "admin", "admin123")
        assert client.post(
            "/api/projects", headers=admin,
            json={"project_id": "actor-tasks", "name": "Actor tasks"},
        ).status_code == 201
        created = client.post(
            "/api/projects/actor-tasks/tasks", headers=admin,
            json=_task_body("pending_confirmation"),
        )
        task_id = created.json()["id"]
        confirmation = client.post(
            f"/api/projects/actor-tasks/tasks/confirmation/{task_id}",
            headers=admin,
            json={"action": "accept", "confirmed_by": "forged-user"},
        )
        assert confirmation.status_code == 200
        assert confirmation.json()["confirmed_by"] == "admin"

        imported = client.post(
            "/api/projects/actor-tasks/tasks/import-confirm",
            headers=admin,
            data={"confirmed_by": "forged-user"},
            files={"file": ("tasks.csv", b"title\nImported task\n", "text/csv")},
        )
        assert imported.status_code == 201
        audit = client.get("/api/projects/actor-tasks/tasks/audit-log", headers=admin)
        assert audit.status_code == 200
        assert any(
            row["entity_type"] == "import"
            and row["operation"] == "confirm_import"
            and row["operator"] == "admin"
            for row in audit.json()
        )
