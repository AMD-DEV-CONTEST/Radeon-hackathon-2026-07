import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.db.models.incident import IncidentSeverity, IncidentStatus


class IncidentCreate(BaseModel):
    title: str
    description: str
    source: str = "manual"
    severity: IncidentSeverity = IncidentSeverity.SEV3
    service_hint: Optional[str] = None
    raw_payload: dict = {}


class EvidenceOut(BaseModel):
    id: uuid.UUID
    evidence_type: str
    source_agent: str
    summary: str
    relevance_score: float

    model_config = {"from_attributes": True}


class AgentStepOut(BaseModel):
    id: uuid.UUID
    agent_name: str
    sequence: int
    output_summary: str
    confidence: Optional[float]
    duration_ms: float
    tokens_per_second: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class IncidentOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    source: str
    severity: IncidentSeverity
    status: IncidentStatus
    root_cause_summary: Optional[str]
    root_cause_confidence: Optional[float]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IncidentDetailOut(IncidentOut):
    evidence: list[EvidenceOut] = []
    agent_steps: list[AgentStepOut] = []


class RemediationApproval(BaseModel):
    approved: bool
    note: Optional[str] = None
