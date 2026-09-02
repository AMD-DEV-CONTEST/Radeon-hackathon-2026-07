"""Resume data access layer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.candidate import Candidate
from models.enums import ResumeStatus
from models.resume import Resume


class ResumeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        candidate_id: UUID,
        file_name: str,
        file_path: str,
        file_type: str | None = None,
        file_size: int | None = None,
        status: ResumeStatus = ResumeStatus.UPLOADED,
        raw_text: str | None = None,
        parsed_data: dict[str, Any] | None = None,
    ) -> Resume:
        resume = Resume(
            candidate_id=candidate_id,
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            file_size=file_size,
            status=status,
            raw_text=raw_text,
            parsed_data=parsed_data,
        )
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        return resume

    def get_by_id(self, resume_id: UUID) -> Resume | None:
        return self.db.get(Resume, resume_id)

    def get_by_id_for_user(self, resume_id: UUID, user_id: UUID) -> Resume | None:
        statement = (
            select(Resume)
            .join(Candidate, Resume.candidate_id == Candidate.id)
            .where(Resume.id == resume_id, Candidate.user_id == user_id)
        )
        return self.db.scalar(statement)

    def list_for_user(
        self,
        user_id: UUID,
        *,
        skip: int,
        limit: int,
        candidate_id: UUID | None = None,
    ) -> tuple[list[Resume], int]:
        filters = [Candidate.user_id == user_id]
        if candidate_id is not None:
            filters.append(Resume.candidate_id == candidate_id)

        total = (
            self.db.scalar(
                select(func.count())
                .select_from(Resume)
                .join(Candidate, Resume.candidate_id == Candidate.id)
                .where(*filters)
            )
            or 0
        )
        statement = (
            select(Resume)
            .join(Candidate, Resume.candidate_id == Candidate.id)
            .where(*filters)
            .order_by(Resume.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(statement)), total

    def update(
        self,
        resume: Resume,
        *,
        file_name: str | None = None,
        file_path: str | None = None,
        file_type: str | None = None,
        file_size: int | None = None,
        status: ResumeStatus | None = None,
        raw_text: str | None = None,
        parsed_data: dict[str, Any] | None = None,
        fields_set: set[str] | None = None,
    ) -> Resume:
        set_fields = fields_set or set()
        if "file_name" in set_fields and file_name is not None:
            resume.file_name = file_name
        if "file_path" in set_fields and file_path is not None:
            resume.file_path = file_path
        if "file_type" in set_fields:
            resume.file_type = file_type
        if "file_size" in set_fields:
            resume.file_size = file_size
        if "status" in set_fields and status is not None:
            resume.status = status
        if "raw_text" in set_fields:
            resume.raw_text = raw_text
        if "parsed_data" in set_fields:
            resume.parsed_data = parsed_data

        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        return resume

    def delete(self, resume: Resume) -> None:
        self.db.delete(resume)
        self.db.commit()
