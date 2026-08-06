"""Skill installation + run records (M7 Skills basic line).

Two tables:
  - skill_installations: a user's "I want skill X on runtime Y, with these params"
  - skill_runs: each execution attempt (queued/running/succeeded/failed)

Skill registry itself lives on disk (app/data/skills_seed.json) and is loaded by
`app.services.skill_registry`. We do not mirror the registry to the DB at this
stage — keeps the seed editable and avoids migration overhead.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, JSON, String, Text, Boolean, UniqueConstraint

from app.models.database import Base, UUIDType


class SkillInstallation(Base):
    __tablename__ = "skill_installations"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", "runtime_id", name="uq_skill_install_user_skill_rt"),
    )

    id = Column(UUIDType, primary_key=True, default=_uuid.uuid4)
    user_id = Column(UUIDType, nullable=False, index=True)
    skill_id = Column(String(128), nullable=False, index=True)
    runtime_id = Column(String(64), nullable=False, index=True)

    enabled = Column(Boolean, nullable=False, default=True)
    params_json = Column(JSON, nullable=True)

    installed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<SkillInstall {self.skill_id}@{self.runtime_id} enabled={self.enabled}>"


class SkillRun(Base):
    __tablename__ = "skill_runs"

    id = Column(UUIDType, primary_key=True, default=_uuid.uuid4)
    user_id = Column(UUIDType, nullable=False, index=True)

    skill_id = Column(String(128), nullable=False, index=True)
    runtime_id = Column(String(64), nullable=False, index=True)
    verb = Column(String(64), nullable=False)

    # "queued" | "running" | "succeeded" | "failed" | "cancelled"
    status = Column(String(16), nullable=False, default="queued", index=True)

    params_json = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    log_excerpt = Column(Text, nullable=True)
    error_msg = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<SkillRun {self.skill_id} status={self.status}>"
