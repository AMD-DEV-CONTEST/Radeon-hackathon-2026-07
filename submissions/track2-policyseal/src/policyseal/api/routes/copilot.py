from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from policyseal.agent.copilot_graph import ReviewCopilot
from policyseal.api.dependencies import AppServices, get_services
from policyseal.api.schemas import (
    ApprovalResponse,
    CopilotMessageInput,
    CopilotReplyResponse,
    CopilotThreadInput,
    CopilotThreadResponse,
    ExceptionDraftResponse,
    ExceptionSubmissionResponse,
    ExceptionSubmitInput,
)

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


def _service(services: AppServices) -> ReviewCopilot:
    if services.copilot is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "copilot_unavailable",
                "message": "The local Review Copilot is not configured.",
            },
        )
    return services.copilot


@router.post(
    "/threads",
    response_model=CopilotThreadResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_thread(
    body: CopilotThreadInput,
    services: Annotated[AppServices, Depends(get_services)],
) -> CopilotThreadResponse:
    thread = _service(services).start_thread(
        body.task_id,
        body.revision_id,
        display_reference=body.display_reference,
    )
    return CopilotThreadResponse.from_domain(thread)


@router.post("/threads/{thread_id}/messages", response_model=CopilotReplyResponse)
def respond(
    thread_id: str,
    body: CopilotMessageInput,
    services: Annotated[AppServices, Depends(get_services)],
) -> CopilotReplyResponse:
    reply = _service(services).respond(
        thread_id,
        task_id=body.task_id,
        message=body.message,
    )
    return CopilotReplyResponse.from_domain(reply)


@router.post(
    "/exception-drafts/{draft_id}/submit",
    response_model=ExceptionSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_exception_draft(
    draft_id: str,
    body: ExceptionSubmitInput,
    services: Annotated[AppServices, Depends(get_services)],
) -> ExceptionSubmissionResponse:
    copilot = _service(services)
    draft = copilot.tools.get_exception_draft(draft_id)
    revision = services.repository.get_revision(draft.revision_id)
    if revision.task_id != draft.task_id:
        raise ValueError("exception draft does not match its revision")
    approval = services.approvals.request(draft.revision_id, actor=body.actor)
    submitted = copilot.tools.mark_exception_submitted(draft.id)
    return ExceptionSubmissionResponse(
        draft=ExceptionDraftResponse.from_domain(submitted),
        approval=ApprovalResponse.from_domain(approval),
    )
