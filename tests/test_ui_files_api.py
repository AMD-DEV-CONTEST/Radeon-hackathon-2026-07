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


def test_project_file_list_and_download_are_project_scoped(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        admin = _token(client, "admin", "admin123")
        guest = _token(client, "guest", "guest123")
        assert client.post(
            "/api/projects", headers=admin,
            json={"project_id": "files-project", "name": "Files"},
        ).status_code == 201
        assert client.post(
            "/api/projects/files-project/files", headers=admin,
            files={"file": ("brief.md", b"# Brief", "text/markdown")},
        ).status_code == 201

        assert client.get("/api/projects/files-project/files").status_code == 401
        assert client.get("/api/projects/files-project/files", headers=guest).status_code == 403
        listed = client.get("/api/projects/files-project/files", headers=admin)
        assert listed.status_code == 200
        assert listed.json() == [{
            "relative_path": "source/brief.md",
            "filename": "brief.md",
            "size_bytes": 7,
            "updated_at": listed.json()[0]["updated_at"],
            "sha256": None,
            "parse_version": None,
            "index_version": None,
            "processing_status": "uploaded",
            "is_task_file": False,
        }]

        download = client.get("/api/projects/files-project/files/download/brief.md", headers=admin)
        assert download.status_code == 200
        assert download.content == b"# Brief"
        assert client.get("/api/projects/files-project/files/download/brief.md", headers=guest).status_code == 403
