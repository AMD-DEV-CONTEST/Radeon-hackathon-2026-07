from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.schemas import Project, ProjectCreate
from app.security.paths import ensure_project_path


class ProjectAlreadyExistsError(RuntimeError):
    pass


class ProjectNotFoundError(RuntimeError):
    pass


def project_paths(project_root: Path, output_root: Path, project_id: str) -> dict[str, Path]:
    """Return the only directories application modules may use for a project."""
    return {
        "project": ensure_project_path(project_root, project_id),
        "source": ensure_project_path(project_root, project_id, "source"),
        "derived": ensure_project_path(project_root, project_id, "derived"),
        "outputs": ensure_project_path(output_root, project_id),
    }


def create_project(project_root: Path, output_root: Path, payload: ProjectCreate) -> Project:
    paths = project_paths(project_root, output_root, payload.project_id)
    metadata_path = paths["project"] / "project.json"
    if paths["project"].exists() or metadata_path.exists():
        raise ProjectAlreadyExistsError(payload.project_id)

    paths["source"].mkdir(parents=True, exist_ok=False)
    paths["derived"].mkdir(parents=True, exist_ok=False)
    paths["outputs"].mkdir(parents=True, exist_ok=True)
    project = Project(**payload.model_dump(), created_at=datetime.now(UTC))
    metadata_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    return project


def get_project(project_root: Path, output_root: Path, project_id: str) -> Project:
    metadata_path = project_paths(project_root, output_root, project_id)["project"] / "project.json"
    if not metadata_path.is_file():
        raise ProjectNotFoundError(project_id)
    try:
        return Project.model_validate(json.loads(metadata_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ProjectNotFoundError(project_id) from error


def list_projects(project_root: Path, output_root: Path) -> list[Project]:
    if not project_root.is_dir():
        return []
    projects: list[Project] = []
    for candidate in project_root.iterdir():
        if not candidate.is_dir():
            continue
        try:
            projects.append(get_project(project_root, output_root, candidate.name))
        except (ProjectNotFoundError, ValueError):
            continue
    return sorted(projects, key=lambda item: item.created_at, reverse=True)
