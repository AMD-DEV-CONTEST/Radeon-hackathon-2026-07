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


def test_core_project_apis_require_login_and_filter_projects(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        admin = _token(client, "admin", "admin123")
        member = _token(client, "member", "member123")

        assert client.get("/api/projects").status_code == 401
        created = client.post("/api/projects", headers=admin, json={"project_id": "private-project", "name": "Private"})
        assert created.status_code == 201
        assert client.post(
            "/api/projects", headers=member,
            json={"project_id": "member-project", "name": "Member"},
        ).status_code == 403
        assert client.get("/api/projects", headers=admin).json()[0]["project_id"] == "private-project"
        assert client.get("/api/projects", headers=member).json() == []
        assert client.get("/api/projects/private-project", headers=member).status_code == 403


def test_core_file_and_run_writes_require_project_member_role(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        admin = _token(client, "admin", "admin123")
        guest = _token(client, "guest", "guest123")
        assert client.post("/api/projects", headers=admin, json={"project_id": "secured-project", "name": "Secured"}).status_code == 201
        assert client.post("/api/projects/secured-project/files", files={"file": ("a.md", b"x", "text/markdown")}).status_code == 401
        assert client.post("/api/projects/secured-project/files", headers=guest, files={"file": ("a.md", b"x", "text/markdown")}).status_code == 403
        assert client.post("/api/projects/secured-project/runs", headers=guest).status_code == 403
        assert client.post("/api/projects/secured-project/runs", headers=admin).status_code == 201
