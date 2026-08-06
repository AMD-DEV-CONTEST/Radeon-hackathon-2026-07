from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from ..exceptions import NotFoundError, ValidationError
from .storage.models import ProjectRow
from .storage.repositories import ProjectRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CreateProjectInput(SQLModel):
    name: str
    description: str | None = None


class ProjectService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._projects = ProjectRepository()

    def create_project(self, input_data: CreateProjectInput) -> ProjectRow:
        name = input_data.name.strip()
        if not name:
            raise ValidationError("Project name cannot be empty.")

        now = _utc_now()
        row = ProjectRow(
            name=name,
            description=input_data.description,
            created_at=now,
            updated_at=now,
        )

        with self._session_factory() as session:
            self._projects.create(session, row)
            session.commit()
            return row

    def list_projects(self) -> list[ProjectRow]:
        with self._session_factory() as session:
            return self._projects.list_all(session)

    def get_project(self, project_id: str) -> ProjectRow:
        with self._session_factory() as session:
            row = self._projects.get(session, project_id)
            if row is None:
                raise NotFoundError(f"Project '{project_id}' was not found.")
            return row
