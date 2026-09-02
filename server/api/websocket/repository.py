"""WebSocket data access helpers (authorization lookups only)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.interview import Interview


class WebSocketRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_interview_for_user(
        self,
        interview_id: UUID,
        user_id: UUID,
    ) -> Interview | None:
        statement = select(Interview).where(
            Interview.id == interview_id,
            Interview.user_id == user_id,
        )
        return self.db.scalar(statement)

    def interview_exists_for_user(self, interview_id: UUID, user_id: UUID) -> bool:
        return self.get_interview_for_user(interview_id, user_id) is not None
