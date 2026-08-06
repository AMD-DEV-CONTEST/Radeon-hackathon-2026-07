from __future__ import annotations

from sqlmodel import Session

from ..models import DatasetColumnBindingRow


class DatasetColumnBindingRepository:
    def create(self, session: Session, row: DatasetColumnBindingRow) -> DatasetColumnBindingRow:
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get(self, session: Session, binding_id: str) -> DatasetColumnBindingRow | None:
        return session.get(DatasetColumnBindingRow, binding_id)
