"""Report data access layer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.enums import Recommendation
from models.interview import Interview
from models.report import Report


class ReportRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        interview_id: UUID,
        overall_score: float | None = None,
        recommendation: Recommendation | None = None,
        performance_confidence: float | None = None,
        summary: str | None = None,
        executive_note: str | None = None,
        competency_matrix: dict[str, Any] | list[Any] | None = None,
        pulse_series: dict[str, Any] | list[Any] | None = None,
        export_path: str | None = None,
    ) -> Report:
        report = Report(
            interview_id=interview_id,
            overall_score=overall_score,
            recommendation=recommendation,
            performance_confidence=performance_confidence,
            summary=summary,
            executive_note=executive_note,
            competency_matrix=competency_matrix,
            pulse_series=pulse_series,
            export_path=export_path,
        )
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def get_by_id(self, report_id: UUID) -> Report | None:
        return self.db.get(Report, report_id)

    def get_by_id_for_user(self, report_id: UUID, user_id: UUID) -> Report | None:
        statement = (
            select(Report)
            .join(Interview, Report.interview_id == Interview.id)
            .where(Report.id == report_id, Interview.user_id == user_id)
        )
        return self.db.scalar(statement)

    def get_by_interview_id(self, interview_id: UUID) -> Report | None:
        statement = select(Report).where(Report.interview_id == interview_id)
        return self.db.scalar(statement)

    def get_by_interview_id_for_user(
        self,
        interview_id: UUID,
        user_id: UUID,
    ) -> Report | None:
        statement = (
            select(Report)
            .join(Interview, Report.interview_id == Interview.id)
            .where(Report.interview_id == interview_id, Interview.user_id == user_id)
        )
        return self.db.scalar(statement)

    def list_for_user(
        self,
        user_id: UUID,
        *,
        skip: int,
        limit: int,
        interview_id: UUID | None = None,
    ) -> tuple[list[Report], int]:
        filters = [Interview.user_id == user_id]
        if interview_id is not None:
            filters.append(Report.interview_id == interview_id)

        total = (
            self.db.scalar(
                select(func.count())
                .select_from(Report)
                .join(Interview, Report.interview_id == Interview.id)
                .where(*filters)
            )
            or 0
        )
        statement = (
            select(Report)
            .join(Interview, Report.interview_id == Interview.id)
            .where(*filters)
            .order_by(Report.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(statement)), total

    def update(
        self,
        report: Report,
        *,
        overall_score: float | None = None,
        recommendation: Recommendation | None = None,
        performance_confidence: float | None = None,
        summary: str | None = None,
        executive_note: str | None = None,
        competency_matrix: dict[str, Any] | list[Any] | None = None,
        pulse_series: dict[str, Any] | list[Any] | None = None,
        export_path: str | None = None,
        fields_set: set[str] | None = None,
    ) -> Report:
        set_fields = fields_set or set()
        if "overall_score" in set_fields:
            report.overall_score = overall_score
        if "recommendation" in set_fields:
            report.recommendation = recommendation
        if "performance_confidence" in set_fields:
            report.performance_confidence = performance_confidence
        if "summary" in set_fields:
            report.summary = summary
        if "executive_note" in set_fields:
            report.executive_note = executive_note
        if "competency_matrix" in set_fields:
            report.competency_matrix = competency_matrix
        if "pulse_series" in set_fields:
            report.pulse_series = pulse_series
        if "export_path" in set_fields:
            report.export_path = export_path

        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def delete(self, report: Report) -> None:
        self.db.delete(report)
        self.db.commit()
