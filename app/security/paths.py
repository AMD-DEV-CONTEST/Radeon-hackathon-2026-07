from __future__ import annotations

import re
from pathlib import Path


PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62})$")


def validate_project_id(project_id: str) -> str:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError(
            "project_id must use 1-63 lowercase letters, digits, or hyphens and start with a letter or digit"
        )
    return project_id


def ensure_project_path(project_root: Path, project_id: str, *parts: str) -> Path:
    """Return a resolved path contained within one project's controlled root."""
    project_id = validate_project_id(project_id)
    root = project_root.resolve()
    project_directory = (root / project_id).resolve()
    try:
        project_directory.relative_to(root)
    except ValueError as error:
        raise ValueError("project directory escapes configured project root") from error

    candidate = (project_directory.joinpath(*parts)).resolve()
    try:
        candidate.relative_to(project_directory)
    except ValueError as error:
        raise ValueError("path escapes project directory") from error
    return candidate
