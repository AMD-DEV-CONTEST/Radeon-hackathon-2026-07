"""
AgentRun / AgentStep — the execution record of the LangGraph investigation.

This is what makes the system *explainable*: every agent invocation, its inputs,
outputs, reasoning, tool calls, latency, and token usage are persisted, so a human
can audit exactly how Aegis reached a conclusion — not just see the final answer.
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, ForeignKey, Enum, Float, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import PortableJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AgentRunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRun(Base):
    """One full LangGraph execution over a single incident."""
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status"), default=AgentRunStatus.RUNNING, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_tokens_generated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    incident: Mapped["Incident"] = relationship(back_populates="agent_runs")
    steps: Mapped[list["AgentStep"]] = relationship(back_populates="agent_run", cascade="all, delete-orphan")


class AgentStep(Base):
    """One node execution within a run — one agent's single turn of reasoning/tool use."""
    __tablename__ = "agent_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "log_analyst"
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # chain-of-thought / justification
    tool_calls: Mapped[list] = mapped_column(PortableJSON, default=list)  # [{tool, args, result}, ...]
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    tokens_generated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_per_second: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    agent_run: Mapped["AgentRun"] = relationship(back_populates="steps")
