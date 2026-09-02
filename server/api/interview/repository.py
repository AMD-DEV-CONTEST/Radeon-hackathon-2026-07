"""Interview data access layer."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.enums import InterviewStatus
from models.interview import Interview


class InterviewRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        candidate_id: UUID,
        user_id: UUID,
        role: str,
        resume_id: UUID | None = None,
        status: InterviewStatus = InterviewStatus.SCHEDULED,
        complexity: str | None = None,
        duration_seconds: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> Interview:
        interview = Interview(
            candidate_id=candidate_id,
            user_id=user_id,
            resume_id=resume_id,
            role=role,
            status=status,
            complexity=complexity,
            duration_seconds=duration_seconds,
            started_at=started_at,
            ended_at=ended_at,
        )
        self.db.add(interview)
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def get_by_id(self, interview_id: UUID) -> Interview | None:
        return self.db.get(Interview, interview_id)

    def get_by_id_for_user(self, interview_id: UUID, user_id: UUID) -> Interview | None:
        statement = select(Interview).where(
            Interview.id == interview_id,
            Interview.user_id == user_id,
        )
        return self.db.scalar(statement)

    def list_for_user(
        self,
        user_id: UUID,
        *,
        skip: int,
        limit: int,
        candidate_id: UUID | None = None,
        status_filter: InterviewStatus | None = None,
    ) -> tuple[list[Interview], int]:
        filters = [Interview.user_id == user_id]
        if candidate_id is not None:
            filters.append(Interview.candidate_id == candidate_id)
        if status_filter is not None:
            filters.append(Interview.status == status_filter)

        total = (
            self.db.scalar(select(func.count()).select_from(Interview).where(*filters)) or 0
        )
        statement = (
            select(Interview)
            .where(*filters)
            .order_by(Interview.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(statement)), total

    def update(
        self,
        interview: Interview,
        *,
        resume_id: UUID | None = None,
        role: str | None = None,
        status: InterviewStatus | None = None,
        score: float | None = None,
        progress: float | None = None,
        complexity: str | None = None,
        duration_seconds: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        fields_set: set[str] | None = None,
    ) -> Interview:
        set_fields = fields_set or set()
        if "resume_id" in set_fields:
            interview.resume_id = resume_id
        if "role" in set_fields and role is not None:
            interview.role = role
        if "status" in set_fields and status is not None:
            interview.status = status
        if "score" in set_fields:
            interview.score = score
        if "progress" in set_fields:
            interview.progress = progress
        if "complexity" in set_fields:
            interview.complexity = complexity
        if "duration_seconds" in set_fields:
            interview.duration_seconds = duration_seconds
        if "started_at" in set_fields:
            interview.started_at = started_at
        if "ended_at" in set_fields:
            interview.ended_at = ended_at

        self.db.add(interview)
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def delete(self, interview: Interview) -> None:
        self.db.delete(interview)
        self.db.commit()
