from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from pydantic import ValidationError

from policyseal.api.dependencies import AppServices, get_services
from policyseal.api.schemas import (
    ContextInput,
    DeletionResponse,
    FormalContextRequest,
    RevisionResponse,
    SimulationRequest,
    SimulationResponse,
    TaskResponse,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_response(services: AppServices, task_id: str) -> TaskResponse:
    task = services.repository.get_task(task_id)
    revisions = tuple(
        RevisionResponse.from_result(services.analysis.get_result(revision.id))
        for revision in services.repository.list_revisions(task.id)
    )
    return TaskResponse(
        id=task.id,
        requester_id=task.requester_id,
        file_kind=task.file_kind,
        source_sha256=task.source.sha256,
        created_at=task.created_at,
        revisions=revisions,
    )


@router.get("", response_model=tuple[TaskResponse, ...])
def list_tasks(services: Annotated[AppServices, Depends(get_services)]) -> tuple[TaskResponse, ...]:
    return tuple(_task_response(services, task.id) for task in services.repository.list_tasks())


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: Request,
    services: Annotated[AppServices, Depends(get_services)],
    file: Annotated[UploadFile, File()],
    context_json: Annotated[str, Form()],
    requester_id: Annotated[str, Form()],
) -> TaskResponse:
    try:
        context = ContextInput.model_validate_json(context_json).to_domain()
    except ValidationError:
        raise ValueError("invalid controlled disclosure context") from None
    max_upload_bytes: int = request.app.state.settings.max_upload_bytes
    source_bytes = await file.read(max_upload_bytes + 1)
    if len(source_bytes) > max_upload_bytes:
        raise ValueError("upload exceeds P0 size limit")
    suffix = Path(file.filename or "").suffix
    result = services.analysis.create_task(
        source_bytes,
        suffix=suffix,
        context=context,
        requester_id=requester_id,
    )
    return _task_response(services, result.task.id)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    services: Annotated[AppServices, Depends(get_services)],
) -> TaskResponse:
    return _task_response(services, task_id)


@router.post("/{task_id}/simulations", response_model=SimulationResponse)
def simulate(
    task_id: str,
    body: SimulationRequest,
    services: Annotated[AppServices, Depends(get_services)],
) -> SimulationResponse:
    simulation = services.simulations.simulate(task_id, body.context.to_domain())
    locations = {
        region.id: region.location
        for region in services.repository.list_regions(simulation.base_revision_id)
    }
    return SimulationResponse.from_domain(
        simulation,
        locations=locations,
    )


@router.post("/{task_id}/formal-context", response_model=RevisionResponse)
def formal_context(
    task_id: str,
    body: FormalContextRequest,
    services: Annotated[AppServices, Depends(get_services)],
) -> RevisionResponse:
    simulation = services.simulations.get(body.simulation_id)
    if simulation.task_id != task_id:
        raise KeyError(task_id)
    return RevisionResponse.from_result(
        services.simulations.confirm_formal(body.simulation_id, actor=body.actor)
    )


@router.delete("/{task_id}", response_model=DeletionResponse)
def delete_task(
    task_id: str,
    actor: Annotated[str, Query(min_length=1)],
    services: Annotated[AppServices, Depends(get_services)],
) -> DeletionResponse:
    tombstone = services.deletion.delete(task_id, actor=actor)
    return DeletionResponse(
        task_id=tombstone.task_id,
        revision_count=tombstone.revision_count,
        source_sha256=tombstone.source_sha256,
        deletion_fingerprint=tombstone.deletion_fingerprint,
    )
