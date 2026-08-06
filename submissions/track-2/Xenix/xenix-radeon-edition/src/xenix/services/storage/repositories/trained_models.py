from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from ..models import TrainedModelRow


class TrainedModelRepository:
    def create(self, session: Session, row: TrainedModelRow) -> TrainedModelRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get(self, session: Session, trained_model_id: str) -> TrainedModelRow | None:
        return session.get(TrainedModelRow, trained_model_id)

    def get_by_ml_task(self, session: Session, ml_task_id: str) -> TrainedModelRow | None:
        statement = select(TrainedModelRow).where(TrainedModelRow.ml_task_id == ml_task_id)
        return session.exec(statement).first()

    def list_by_dataset(self, session: Session, dataset_id: str) -> list[TrainedModelRow]:
        statement = (
            select(TrainedModelRow)
            .where(TrainedModelRow.dataset_id == dataset_id)
            .order_by(TrainedModelRow.created_at)
        )
        return list(session.exec(statement))

    def update_metadata(
        self,
        session: Session,
        trained_model_id: str,
        metadata_payload: dict,
        now: datetime,
    ) -> TrainedModelRow | None:
        row = self.get(session, trained_model_id)
        if row is None:
            return None
        row.metadata_payload = dict(metadata_payload)
        row.updated_at = now
        session.add(row)
        session.flush()
        session.refresh(row)
        return row
