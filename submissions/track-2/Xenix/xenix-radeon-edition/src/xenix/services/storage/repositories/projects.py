from __future__ import annotations

from sqlmodel import Session, select

from ..models import ProjectRow


class ProjectRepository:
    def create(self, session: Session, row: ProjectRow) -> ProjectRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get(self, session: Session, project_id: str) -> ProjectRow | None:
        return session.get(ProjectRow, project_id)

    def list_all(self, session: Session) -> list[ProjectRow]:
        statement = select(ProjectRow).order_by(ProjectRow.created_at)
        return list(session.exec(statement))
