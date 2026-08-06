"""Copilot Playbook — structured troubleshooting knowledge base."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, JSON, String, Text

from app.models.database import Base


class CopilotPlaybook(Base):
    __tablename__ = "copilot_playbooks"

    code = Column(String(64), primary_key=True)
    title = Column(String(256), nullable=False)
    severity = Column(String(16), nullable=False, default="warning")
    pages = Column(JSON, nullable=False, default=list)
    symptoms = Column(JSON, nullable=False, default=list)
    diagnostic_keys = Column(JSON, nullable=False, default=list)
    root_cause = Column(Text, nullable=False)
    fix_steps = Column(JSON, nullable=False, default=list)
    verify_steps = Column(JSON, nullable=False, default=list)
    safe_to_show = Column(Boolean, nullable=False, default=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CopilotPlaybook {self.code} {self.severity}>"
