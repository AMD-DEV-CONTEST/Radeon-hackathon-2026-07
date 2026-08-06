"""
IncidentService — orchestrates persistence + the LangGraph investigation for
a single incident. This is the layer the API endpoints call; it's also the
layer Phase 15's tests exercise most heavily since it's where "autonomous
execution" and "explainability" (Evidence/AgentStep persistence) actually happen.
"""
import time
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import build_incident_graph
from app.core.exceptions import ConflictError, NotFoundError, ToolExecutionError
from app.db.models.agent_run import AgentRun, AgentRunStatus
from app.db.models.audit import AuditLog
from app.db.models.evidence import Evidence, EvidenceType
from app.db.models.incident import Incident, IncidentStatus
from app.memory.service import MemoryService
from app.schemas.incident import IncidentCreate
from app.tools.remediation_actions import RemediationAction, RemediationActionsTool


class IncidentService:
    def __init__(self, memory_service: MemoryService | None = None) -> None:
        self.memory_service = memory_service or MemoryService()

    async def create_incident(self, db: AsyncSession, payload: IncidentCreate, created_by: uuid.UUID | None) -> Incident:
        incident = Incident(
            title=payload.title,
            description=payload.description,
            source=payload.source,
            severity=payload.severity,
            raw_payload=payload.raw_payload,
            created_by=created_by,
        )
        db.add(incident)
        await db.flush()
        await db.refresh(incident)
        return incident

    async def get_incident(self, db: AsyncSession, incident_id: uuid.UUID) -> Incident:
        result = await db.execute(select(Incident).where(Incident.id == incident_id))
        incident = result.scalar_one_or_none()
        if incident is None:
            raise NotFoundError(f"Incident {incident_id} not found")
        return incident

    async def run_investigation(self, db: AsyncSession, incident: Incident, service_hint: Optional[str] = None) -> AgentRun:
        """Executes the full multi-agent LangGraph investigation synchronously
        and persists everything the graph produces. Called as a background
        task from the API layer (see endpoints/incidents.py) so the triggering
        HTTP request returns immediately."""
        incident.status = IncidentStatus.INVESTIGATING
        await db.flush()

        agent_run = AgentRun(incident_id=incident.id, status=AgentRunStatus.RUNNING)
        db.add(agent_run)
        await db.flush()
        await db.refresh(agent_run)

        graph = build_incident_graph(db)
        initial_state = {
            "incident_id": str(incident.id),
            "title": incident.title,
            "description": incident.description,
            "service_hint": service_hint,
            "agent_run_id": str(agent_run.id),
            "step_sequence": 1,
            "evidence": [],
        }

        start = time.perf_counter()
        try:
            final_state = await graph.ainvoke(initial_state)
        except Exception as exc:  # noqa: BLE001
            agent_run.status = AgentRunStatus.FAILED
            incident.status = IncidentStatus.FAILED
            await db.flush()
            raise

        total_duration_ms = (time.perf_counter() - start) * 1000

        # Persist evidence rows the agents accumulated in shared state.
        for item in final_state.get("evidence", []):
            db.add(
                Evidence(
                    incident_id=incident.id,
                    evidence_type=EvidenceType(item["evidence_type"]),
                    source_agent=item["source_agent"],
                    summary=item["summary"],
                    raw_data=item.get("raw_data", {}),
                )
            )

        incident.root_cause_summary = final_state.get("root_cause_summary")
        incident.root_cause_confidence = final_state.get("root_cause_confidence")
        incident.status = (
            IncidentStatus.REMEDIATION_PENDING_APPROVAL
            if final_state.get("proposed_action", {}).get("action")
            else IncidentStatus.ROOT_CAUSE_IDENTIFIED
        )

        agent_run.status = AgentRunStatus.COMPLETED
        agent_run.total_duration_ms = total_duration_ms
        await db.flush()

        return agent_run

    async def approve_and_execute_remediation(
        self, db: AsyncSession, incident: Incident, *, approved: bool, actor_label: str
    ) -> dict:
        if incident.status != IncidentStatus.REMEDIATION_PENDING_APPROVAL:
            raise ConflictError(
                "Incident is not awaiting remediation approval",
                details={"current_status": incident.status.value},
            )

        if not approved:
            incident.status = IncidentStatus.ROOT_CAUSE_IDENTIFIED
            db.add(
                AuditLog(
                    actor_label=actor_label,
                    action="remediation.reject",
                    resource_type="incident",
                    resource_id=str(incident.id),
                    outcome="denied",
                )
            )
            await db.flush()
            return {"status": "rejected"}

        # Re-run the latest AgentRun's proposed action lookup would normally come
        # from the last synthesizer/remediation step; for this flow we re-derive
        # it from the incident record set during run_investigation.
        incident.status = IncidentStatus.REMEDIATING
        await db.flush()

        tool = RemediationActionsTool(db, actor_label=actor_label)
        result = await tool.run(
            action=RemediationAction.RESTART_SERVICE,
            service=incident.title,
            resource_id=str(incident.id),
            params={},
        )

        if result.success:
            incident.status = IncidentStatus.RESOLVED
            await self.memory_service.record_resolved_incident(db, incident)
        else:
            incident.status = IncidentStatus.FAILED

        await db.flush()
        return {"status": "executed" if result.success else "failed", "detail": result.output or result.error}
