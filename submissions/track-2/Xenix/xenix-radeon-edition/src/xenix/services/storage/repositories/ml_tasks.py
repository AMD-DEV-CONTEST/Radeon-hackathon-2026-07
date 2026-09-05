from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from ..models import MLTaskArtifactRow, MLTaskRow, MLTaskStatus


class MLTaskRepository:
    def create(self, session: Session, row: MLTaskRow) -> MLTaskRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get(self, session: Session, ml_task_id: str) -> MLTaskRow | None:
        return session.get(MLTaskRow, ml_task_id)

    def list_by_dataset(self, session: Session, dataset_id: str) -> list[MLTaskRow]:
        statement = (
            select(MLTaskRow)
            .where(MLTaskRow.dataset_id == dataset_id)
            .order_by(MLTaskRow.created_at)
        )
        return list(session.exec(statement))

    def update_status(
        self,
        session: Session,
        ml_task_id: str,
        from_status: MLTaskStatus,
        to_status: MLTaskStatus,
        now: datetime,
    ) -> MLTaskRow | None:
        row = self.get(session, ml_task_id)
        if row is None or row.status != from_status:
            return None

        row.status = to_status
        row.updated_at = now
        if to_status is MLTaskStatus.RUNNING and row.started_at is None:
            row.started_at = now
        if to_status in {MLTaskStatus.SUCCEEDED, MLTaskStatus.FAILED, MLTaskStatus.CANCELLED}:
            row.finished_at = now
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def complete(
        self,
        session: Session,
        ml_task_id: str,
        result_payload: dict[str, Any],
        finished_at: datetime,
        artifacts: list[MLTaskArtifactRow],
    ) -> MLTaskRow | None:
        row = self.get(session, ml_task_id)
        if row is None:
            return None

        row.status = MLTaskStatus.SUCCEEDED
        row.result_payload = result_payload
        row.error_summary = None
        row.finished_at = finished_at
        row.updated_at = finished_at
        session.add(row)
        for artifact in artifacts:
            session.add(artifact)
        session.flush()
        session.refresh(row)
        return row

    def fail(self, session: Session, ml_task_id: str, error_summary: str, finished_at: datetime) -> MLTaskRow | None:
        row = self.get(session, ml_task_id)
        if row is None:
            return None

        row.status = MLTaskStatus.FAILED
        row.error_summary = error_summary
        row.finished_at = finished_at
        row.updated_at = finished_at
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def cancel(self, session: Session, ml_task_id: str, finished_at: datetime) -> MLTaskRow | None:
        row = self.get(session, ml_task_id)
        if row is None:
            return None

        row.status = MLTaskStatus.CANCELLED
        row.finished_at = finished_at
        row.updated_at = finished_at
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def list_artifacts(self, session: Session, ml_task_id: str) -> list[MLTaskArtifactRow]:
        statement = (
            select(MLTaskArtifactRow)
            .where(MLTaskArtifactRow.ml_task_id == ml_task_id)
            .order_by(MLTaskArtifactRow.created_at)
        )
        return list(session.exec(statement))
