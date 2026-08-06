"""
Incident API — full implementation.

Investigation runs as a FastAPI BackgroundTask so POST /incidents returns
immediately (202-style UX) while the multi-agent graph executes; the
frontend (Phase 12) polls GET /incidents/{id} or subscribes to the SSE
stream to watch it progress in near-real-time.
"""
import asyncio
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.models.agent_run import AgentRun, AgentStep
from app.db.models.evidence import Evidence
from app.db.models.incident import Incident
from app.db.models.user import Role, User
from app.db.session import AsyncSessionLocal, get_db
from app.schemas.incident import (
    AgentStepOut,
    EvidenceOut,
    IncidentCreate,
    IncidentDetailOut,
    IncidentOut,
    RemediationApproval,
)
from app.services.incident_service import IncidentService

router = APIRouter()
_service = IncidentService()


async def _run_investigation_background(incident_id: uuid.UUID, service_hint: str | None) -> None:
    """Runs in its own DB session since BackgroundTasks execute after the
    request's session has already been closed."""
    async with AsyncSessionLocal() as db:
        try:
            incident = await _service.get_incident(db, incident_id)
            await _service.run_investigation(db, incident, service_hint=service_hint)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


@router.post("", response_model=IncidentOut, status_code=202)
async def create_incident(
    payload: IncidentCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IncidentOut:
    incident = await _service.create_incident(db, payload, created_by=current_user.id)
    await db.flush()
    incident_id = incident.id
    background_tasks.add_task(_run_investigation_background, incident_id, payload.service_hint)
    return IncidentOut.model_validate(incident)


@router.get("", response_model=list[IncidentOut])
async def list_incidents(db: AsyncSession = Depends(get_db)) -> list[IncidentOut]:
    result = await db.execute(select(Incident).order_by(Incident.created_at.desc()).limit(100))
    return [IncidentOut.model_validate(i) for i in result.scalars().all()]


@router.get("/{incident_id}", response_model=IncidentDetailOut)
async def get_incident(incident_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> IncidentDetailOut:
    incident = await _service.get_incident(db, incident_id)

    evidence_result = await db.execute(select(Evidence).where(Evidence.incident_id == incident_id))
    steps_result = await db.execute(
        select(AgentStep)
        .join(AgentRun, AgentStep.agent_run_id == AgentRun.id)
        .where(AgentRun.incident_id == incident_id)
        .order_by(AgentStep.created_at)
    )

    # Built from the already-validated IncidentOut rather than
    # IncidentDetailOut.model_validate(incident) directly — the ORM's
    # `evidence` relationship attribute would otherwise be touched during
    # attribute extraction and trigger an implicit lazy-load, which async
    # SQLAlchemy sessions don't support outside an explicit await.
    base = IncidentOut.model_validate(incident)
    detail = IncidentDetailOut(
        **base.model_dump(),
        evidence=[EvidenceOut.model_validate(e) for e in evidence_result.scalars().all()],
        agent_steps=[AgentStepOut.model_validate(s) for s in steps_result.scalars().all()],
    )
    return detail


@router.post("/{incident_id}/remediation/approve")
async def approve_remediation(
    incident_id: uuid.UUID,
    payload: RemediationApproval,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(Role.SRE)),
) -> dict:
    incident = await _service.get_incident(db, incident_id)
    result = await _service.approve_and_execute_remediation(
        db, incident, approved=payload.approved, actor_label=f"user:{current_user.email}"
    )
    return result


@router.get("/{incident_id}/stream")
async def stream_incident_progress(incident_id: uuid.UUID) -> StreamingResponse:
    """
    Server-Sent Events endpoint the frontend subscribes to for a live view of
    the investigation as agent steps are persisted — this is what turns
    "explainability" into something a human watches happen, not just a report
    read after the fact.
    """
    async def event_generator():
        last_seen = 0
        for _ in range(120):  # ~2 minutes of polling at 1s intervals, then the client reconnects
            async with AsyncSessionLocal() as db:
                incident = await db.get(Incident, incident_id)
                if incident is None:
                    yield "event: error\ndata: incident not found\n\n"
                    return

                steps_result = await db.execute(
                    select(AgentStep)
                    .join(AgentStep.agent_run)
                    .where(AgentStep.agent_run.has(incident_id=incident_id))
                    .order_by(AgentStep.created_at)
                )
                steps = list(steps_result.scalars().all())

                for step in steps[last_seen:]:
                    yield (
                        f"event: agent_step\n"
                        f"data: {step.agent_name} completed in {step.duration_ms:.0f}ms "
                        f"(confidence={step.confidence})\n\n"
                    )
                last_seen = len(steps)

                if incident.status.value in (
                    "resolved", "root_cause_identified", "failed", "remediation_pending_approval",
                ):
                    yield f"event: done\ndata: status={incident.status.value}\n\n"
                    return

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
