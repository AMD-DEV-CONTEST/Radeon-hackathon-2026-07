from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security.paths import ensure_project_path


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


def test_project_api_creates_isolated_directories_and_metadata(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/projects", json={"project_id": "demo-project", "name": "Demo project"}
        )
        assert response.status_code == 201
        assert response.json()["status"] == "created"
        assert "root" not in response.json()

        read_response = client.get("/api/projects/demo-project")
        assert read_response.status_code == 200
        assert read_response.json()["name"] == "Demo project"

        assert client.post(
            "/api/projects", json={"project_id": "demo-project", "name": "Duplicate"}
        ).status_code == 409
        assert client.get("/api/projects/missing-project").status_code == 404
        assert client.post(
            "/api/projects", json={"project_id": "../outside", "name": "Invalid"}
        ).status_code == 422

    assert (tmp_path / "projects" / "demo-project" / "source").is_dir()
    assert (tmp_path / "projects" / "demo-project" / "derived").is_dir()
    assert (tmp_path / "outputs" / "demo-project").is_dir()


def test_controlled_path_rejects_traversal(tmp_path: Path) -> None:
    safe_path = ensure_project_path(tmp_path / "projects", "demo", "source", "brief.md")
    assert safe_path == (tmp_path / "projects" / "demo" / "source" / "brief.md").resolve()
    try:
        ensure_project_path(tmp_path / "projects", "demo", "..", "other-project")
    except ValueError as error:
        assert "escapes project directory" in str(error)
    else:
        raise AssertionError("expected traversal path rejection")


def test_project_list_and_uploads_are_project_scoped(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        assert client.post("/api/projects", json={"project_id": "demo", "name": "Demo"}).status_code == 201
        assert client.get("/api/projects").json()[0]["project_id"] == "demo"

        reference = client.post(
            "/api/projects/demo/files",
            files={"file": ("status.md", b"# Status\nAPI verification is completed.", "text/markdown")},
        )
        assert reference.status_code == 201
        assert reference.json()["relative_path"] == "source/status.md"

        task = client.post(
            "/api/projects/demo/files",
            data={"task_file": "true"},
            files={"file": ("weekly-input.csv", b"title,assignee\nAPI verification,Ada\n", "text/csv")},
        )
        assert task.status_code == 201
        assert task.json()["relative_path"] == "source/tasks.csv"

        assert client.post(
            "/api/projects/demo/files",
            files={"file": ("../escape.md", b"no", "text/markdown")},
        ).status_code == 422
        assert client.post(
            "/api/projects/demo/files",
            files={"file": ("unsafe.exe", b"no", "application/octet-stream")},
        ).status_code == 422
