from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from ..models import DatasetRow


class DatasetRepository:
    def create(self, session: Session, row: DatasetRow) -> DatasetRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get(self, session: Session, dataset_id: str) -> DatasetRow | None:
        return session.get(DatasetRow, dataset_id)

    def list_by_project(self, session: Session, project_id: str) -> list[DatasetRow]:
        statement = (
            select(DatasetRow)
            .where(DatasetRow.project_id == project_id)
            .order_by(DatasetRow.created_at)
        )
        return list(session.exec(statement))

    def list_all(self, session: Session) -> list[DatasetRow]:
        statement = select(DatasetRow).order_by(DatasetRow.created_at)
        return list(session.exec(statement))

    def list_source_by_project(self, session: Session, project_id: str) -> list[DatasetRow]:
        statement = (
            select(DatasetRow)
            .where(
                and_(
                    DatasetRow.project_id == project_id,
                    DatasetRow.copied_from.is_(None),
                    DatasetRow.derived_from_dataset_id.is_(None),
                    DatasetRow.ml_task_id.is_(None),
                )
            )
            .order_by(DatasetRow.created_at)
        )
        return list(session.exec(statement))

    def list_sources(self, session: Session) -> list[DatasetRow]:
        statement = (
            select(DatasetRow)
            .where(
                and_(
                    DatasetRow.copied_from.is_(None),
                    DatasetRow.derived_from_dataset_id.is_(None),
                    DatasetRow.ml_task_id.is_(None),
                )
            )
            .order_by(DatasetRow.created_at)
        )
        return list(session.exec(statement))

    def list_generated_by_project(self, session: Session, project_id: str) -> list[DatasetRow]:
        statement = (
            select(DatasetRow)
            .where(
                and_(
                    DatasetRow.project_id == project_id,
                    or_(
                        DatasetRow.ml_task_id.is_not(None),
                        DatasetRow.derived_from_dataset_id.is_not(None),
                    ),
                )
            )
            .order_by(DatasetRow.created_at)
        )
        return list(session.exec(statement))

    def list_generated(self, session: Session) -> list[DatasetRow]:
        statement = (
            select(DatasetRow)
            .where(
                or_(
                    DatasetRow.ml_task_id.is_not(None),
                    DatasetRow.derived_from_dataset_id.is_not(None),
                )
            )
            .order_by(DatasetRow.created_at)
        )
        return list(session.exec(statement))

    def list_copies_by_source(self, session: Session, source_dataset_id: str) -> list[DatasetRow]:
        statement = (
            select(DatasetRow)
            .where(DatasetRow.copied_from == source_dataset_id)
            .order_by(DatasetRow.created_at)
        )
        return list(session.exec(statement))

    def list_derived_by_source(self, session: Session, source_dataset_id: str) -> list[DatasetRow]:
        statement = (
            select(DatasetRow)
            .where(DatasetRow.derived_from_dataset_id == source_dataset_id)
            .order_by(DatasetRow.created_at)
        )
        return list(session.exec(statement))

    def get_by_ml_task(self, session: Session, ml_task_id: str) -> DatasetRow | None:
        statement = select(DatasetRow).where(DatasetRow.ml_task_id == ml_task_id)
        return session.exec(statement).first()

    def rename(self, session: Session, dataset_id: str, new_name: str, now: datetime) -> DatasetRow | None:
        row = self.get(session, dataset_id)
        if row is None:
            return None

        row.name = new_name
        row.updated_at = now
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def delete(self, session: Session, row: DatasetRow) -> None:
        session.delete(row)
        session.flush()
