"""
Import every model module here so that Base.metadata is fully populated
whenever `from app.db.models import Base` (or Alembic's env.py) runs.
"""
from app.db.session import Base
from app.db.models.user import User, Role
from app.db.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.db.models.agent_run import AgentRun, AgentStep, AgentRunStatus
from app.db.models.evidence import Evidence, EvidenceType
from app.db.models.memory import MemoryRecord, MemoryKind, EMBEDDING_DIM
from app.db.models.audit import AuditLog

__all__ = [
    "Base", "User", "Role",
    "Incident", "IncidentSeverity", "IncidentStatus",
    "AgentRun", "AgentStep", "AgentRunStatus",
    "Evidence", "EvidenceType",
    "MemoryRecord", "MemoryKind", "EMBEDDING_DIM",
    "AuditLog",
]
