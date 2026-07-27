"""Versioned HTTP API for XiangLens."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile, status
from starlette.background import BackgroundTask
from starlette.responses import FileResponse, StreamingResponse

from xianglens import __version__
from xianglens.inference.llama_client import ModelNotConfiguredError, ModelRequestError
from xianglens.schemas import (
    LENS_PACKS,
    AccessSession,
    AnalysisRunRequest,
    AnalysisRunResponse,
    ConsentDecision,
    ForgetMeResult,
    ImageSummary,
    MemoryProposal,
    MemoryProposalCreate,
    MemoryRecord,
    PerformanceMetrics,
    RunRecord,
    SystemStatus,
    ThreadCreate,
    ThreadDetail,
    ThreadSummary,
)
from xianglens.services import AppServices
from xianglens.tools.image_tools import ImageValidationError

LOGGER = logging.getLogger(__name__)
router = APIRouter()


def _services(request: Request) -> AppServices:
    return request.app.state.services


def _safe_endpoint(value: str) -> str:
    if not value:
        return "not configured"
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, host + port, parsed.path, "", ""))


def _session_user_id(request: Request) -> str | None:
    return getattr(request.state, "session_user_id", None)


def _scope_user(request: Request, requested_user_id: str) -> str:
    session_user_id = _session_user_id(request)
    if session_user_id is not None and session_user_id != requested_user_id:
        raise HTTPException(
            status_code=403,
            detail="The access session cannot use another identity",
        )
    return session_user_id or requested_user_id


def _require_thread(
    services: AppServices, thread_id: str, session_user_id: str | None = None
) -> dict:
    thread = services.database.get_thread(thread_id)
    if thread is None or (session_user_id is not None and thread["user_id"] != session_user_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


def _performance_metrics(result: dict, image_count: int) -> PerformanceMetrics:
    traces = result.get("tool_trace", [])
    local_tools = {"image_measurement_and_privacy_scan"}
    model_tools = {
        "self_hosted_vlm",
        "self_hosted_llm_and_safe_renderer",
        "consent_first_memory",
        "transparent_comparison_rubric",
    }
    return PerformanceMetrics(
        total_duration_ms=round(sum(item.get("duration_ms", 0.0) for item in traces), 2),
        local_tool_duration_ms=round(
            sum(item.get("duration_ms", 0.0) for item in traces if item.get("tool") in local_tools),
            2,
        ),
        model_duration_ms=round(
            sum(
                item.get("duration_ms", 0.0)
                for item in traces
                if item.get("tool") in model_tools and item.get("status") != "skipped"
            ),
            2,
        ),
        retrieval_duration_ms=round(
            sum(
                item.get("duration_ms", 0.0) for item in traces if item.get("tool") == "milvus_lite"
            ),
            2,
        ),
        image_count=image_count,
        evidence_count=len(result.get("evidence", [])),
    )


def _start_analysis(
    services: AppServices,
    thread_id: str,
    payload: AnalysisRunRequest,
    session_user_id: str | None = None,
) -> tuple[dict, list[dict], str, dict]:
    thread = _require_thread(services, thread_id, session_user_id)
    unknown_packs = sorted(set(payload.enabled_packs) - set(LENS_PACKS))
    if unknown_packs:
        raise HTTPException(status_code=422, detail=f"Unknown Lens Packs: {unknown_packs}")
    images = services.database.get_images(thread_id, payload.image_ids)
    if len(images) != len(payload.image_ids):
        raise HTTPException(status_code=404, detail="One or more image IDs were not found")
    run_id = services.database.start_run(thread_id, payload.model_dump())
    initial_state = {
        "run_id": run_id,
        "thread_id": thread_id,
        "user_id": thread["user_id"],
        "message": payload.message,
        "platform": payload.platform,
        "audience": payload.audience,
        "intent_keywords": payload.intent_keywords,
        "enabled_packs": payload.enabled_packs,
        "image_paths": [Path(item["path"]) for item in images],
        "tool_trace": [],
    }
    return thread, images, run_id, initial_state


def _finalize_analysis(
    services: AppServices,
    *,
    thread_id: str,
    thread: dict,
    images: list[dict],
    run_id: str,
    message: str,
    result: dict,
) -> AnalysisRunResponse:
    run_status = "blocked" if result.get("blocked_reason") else "completed"
    memory_proposal = None
    if draft := result.get("memory_proposal_draft"):
        stored_proposal = services.database.create_memory_proposal(
            thread_id=thread_id,
            user_id=thread["user_id"],
            text=draft["text"],
            memory_type=draft["memory_type"],
        )
        memory_proposal = MemoryProposal.model_validate(stored_proposal)
    response = AnalysisRunResponse(
        run_id=run_id,
        thread_id=thread_id,
        status=run_status,
        plan=result.get("plan", []),
        observations=[
            *result.get("measurements", []),
            *result.get("visual_observations", []),
        ],
        privacy_findings=result.get("privacy_findings", []),
        evidence=result.get("evidence", []),
        recalled_memories=result.get("recalled_memories", []),
        comparison=result.get("comparison"),
        memory_proposal=memory_proposal,
        report_markdown=result.get("report_markdown", ""),
        tool_trace=result.get("tool_trace", []),
        performance_metrics=_performance_metrics(result, len(images)),
    )
    services.database.finish_run(run_id, run_status, response.model_dump(mode="json"))
    services.database.add_message(thread_id, "user", message)
    services.database.add_message(thread_id, "assistant", response.report_markdown)
    return response


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "xianglens"}


@router.post(
    "/api/v1/session",
    response_model=AccessSession,
    status_code=status.HTTP_201_CREATED,
)
async def create_access_session(request: Request, response: Response) -> AccessSession:
    services = _services(request)
    settings = services.settings
    manager = request.app.state.session_tokens
    if not settings.auth_enabled or not settings.public_sessions_enabled or manager is None:
        raise HTTPException(status_code=404, detail="Access-session issuance is not enabled")

    client_key = request.client.host if request.client is not None else "unknown"
    retry_after = request.app.state.session_limiter.retry_after(client_key)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many access-session requests",
            headers={"Retry-After": str(retry_after)},
        )

    token, claims = manager.issue()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return AccessSession(
        access_token=token,
        expires_in=manager.ttl_seconds,
        expires_at=datetime.fromtimestamp(claims.expires_at, UTC),
        session_id=claims.session_id,
    )


@router.get("/api/v1/system/status", response_model=SystemStatus)
async def system_status(
    request: Request, probe_model: Annotated[bool, Query()] = False
) -> SystemStatus:
    services = _services(request)
    settings = services.settings
    reachable: bool | None = None
    if probe_model and settings.model_configured:
        reachable = await services.model.health()
    return SystemStatus(
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        deployment_mode=settings.deployment_mode,
        auth_enabled=settings.auth_enabled,
        model_configured=settings.model_configured,
        model_reachable=reachable,
        model_endpoint=_safe_endpoint(settings.llm_base_url),
        model_name=settings.llm_model,
        inference_ownership="user-controlled self-hosted llama.cpp on AMD Radeon/ROCm",
        submission_topology_compliant=settings.submission_topology_compliant,
        milvus_uri=str(settings.milvus_uri),
        milvus_ready=services.knowledge.is_ready(),
        sqlite_path=str(settings.sqlite_path),
    )


@router.get("/api/v1/lens-packs")
async def lens_packs() -> dict[str, list[str]]:
    return {"lens_packs": list(LENS_PACKS)}


@router.post("/api/v1/threads", response_model=ThreadSummary, status_code=status.HTTP_201_CREATED)
async def create_thread(payload: ThreadCreate, request: Request) -> dict:
    user_id = _scope_user(request, payload.user_id)
    return _services(request).database.create_thread(user_id)


@router.get("/api/v1/threads/{thread_id}", response_model=ThreadSummary)
async def get_thread(thread_id: str, request: Request) -> dict:
    return _require_thread(_services(request), thread_id, _session_user_id(request))


@router.get("/api/v1/threads/{thread_id}/state", response_model=ThreadDetail)
async def get_thread_state(thread_id: str, request: Request) -> dict:
    services = _services(request)
    thread = _require_thread(services, thread_id, _session_user_id(request))
    return {
        **thread,
        "images": services.database.list_images(thread_id),
        "messages": services.database.list_messages(thread_id, limit=50),
    }


@router.get("/api/v1/threads/{thread_id}/runs", response_model=list[RunRecord])
async def list_thread_runs(thread_id: str, request: Request) -> list[dict]:
    services = _services(request)
    _require_thread(services, thread_id, _session_user_id(request))
    return services.database.list_runs(thread_id)


@router.get("/api/v1/runs/{run_id}", response_model=RunRecord)
async def get_run(run_id: str, request: Request) -> dict:
    run = _services(request).database.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    _require_thread(_services(request), run["thread_id"], _session_user_id(request))
    return run


@router.delete("/api/v1/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(thread_id: str, request: Request) -> None:
    services = _services(request)
    _require_thread(services, thread_id, _session_user_id(request))
    for stored_path in services.database.delete_thread(thread_id):
        path = Path(stored_path).resolve()
        try:
            path.relative_to(services.settings.upload_dir.resolve())
        except ValueError:
            LOGGER.error("Refused to delete an image outside the controlled upload directory")
            continue
        path.unlink(missing_ok=True)


@router.post(
    "/api/v1/threads/{thread_id}/images",
    response_model=ImageSummary,
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    thread_id: str,
    request: Request,
    image: Annotated[UploadFile, File(description="JPEG, PNG, or WebP image")],
) -> dict:
    services = _services(request)
    _require_thread(services, thread_id, _session_user_id(request))
    data = await image.read(services.settings.max_upload_bytes + 1)
    try:
        details = services.image_inspector.validate_upload(data)
    except ImageValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    image_id = uuid.uuid4().hex
    thread_dir = services.settings.upload_dir / thread_id
    thread_dir.mkdir(parents=True, exist_ok=True)
    path = thread_dir / f"{image_id}{details['extension']}"
    path.write_bytes(data)
    return services.database.add_image(
        image_id=image_id,
        thread_id=thread_id,
        path=path,
        original_name=Path(image.filename or "upload").name,
        mime_type=details["mime_type"],
        width=details["width"],
        height=details["height"],
        digest=details["sha256"],
    )


@router.post("/api/v1/threads/{thread_id}/images/{image_id}/safe-copy")
async def export_safe_copy(thread_id: str, image_id: str, request: Request) -> FileResponse:
    services = _services(request)
    _require_thread(services, thread_id, _session_user_id(request))
    image = services.database.get_image(thread_id, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    export_path = services.settings.export_dir / f"xianglens-safe-{uuid.uuid4().hex}.jpg"
    try:
        details = services.image_inspector.export_safe_copy(Path(image["path"]), export_path)
    except ImageValidationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    services.database.audit(
        "safe_copy_exported",
        f"Exported metadata-free JPEG {details['sha256'][:12]} ({details['bytes']} bytes).",
        thread_id,
    )
    return FileResponse(
        export_path,
        media_type="image/jpeg",
        filename=f"xianglens-safe-{image_id}.jpg",
        background=BackgroundTask(export_path.unlink, missing_ok=True),
        headers={
            "X-XiangLens-SHA256": details["sha256"],
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/api/v1/threads/{thread_id}/runs",
    response_model=AnalysisRunResponse,
)
async def run_analysis(
    thread_id: str, payload: AnalysisRunRequest, request: Request
) -> AnalysisRunResponse:
    services = _services(request)
    thread, images, run_id, initial_state = _start_analysis(
        services, thread_id, payload, _session_user_id(request)
    )
    try:
        result = await services.graph.ainvoke(initial_state)
        return _finalize_analysis(
            services,
            thread_id=thread_id,
            thread=thread,
            images=images,
            run_id=run_id,
            message=payload.message,
            result=result,
        )
    except (ModelNotConfiguredError, ModelRequestError) as exc:
        services.database.finish_run(run_id, "failed", {"error": str(exc)})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Analysis run failed")
        services.database.finish_run(run_id, "failed", {"error": "internal error"})
        raise HTTPException(status_code=500, detail="Analysis run failed") from exc


@router.post("/api/v1/threads/{thread_id}/runs/stream")
async def stream_analysis(
    thread_id: str, payload: AnalysisRunRequest, request: Request
) -> StreamingResponse:
    services = _services(request)
    thread, images, run_id, initial_state = _start_analysis(
        services, thread_id, payload, _session_user_id(request)
    )

    async def event_stream() -> AsyncIterator[str]:
        state = dict(initial_state)
        finalized = False
        yield _sse(
            "run.started",
            {"run_id": run_id, "thread_id": thread_id, "image_count": len(images)},
        )
        try:
            async for update in services.graph.astream(initial_state, stream_mode="updates"):
                for node, node_update in update.items():
                    if not isinstance(node_update, dict):
                        continue
                    state.update(node_update)
                    traces = node_update.get("tool_trace", [])
                    latest_trace = traces[-1] if traces else None
                    yield _sse(
                        "node.completed",
                        {
                            "run_id": run_id,
                            "node": node,
                            "trace": latest_trace,
                            "plan": node_update.get("plan"),
                        },
                    )
            response = _finalize_analysis(
                services,
                thread_id=thread_id,
                thread=thread,
                images=images,
                run_id=run_id,
                message=payload.message,
                result=state,
            )
            finalized = True
            yield _sse("run.completed", response.model_dump(mode="json"))
        except (ModelNotConfiguredError, ModelRequestError) as exc:
            services.database.finish_run(run_id, "failed", {"error": str(exc)})
            finalized = True
            yield _sse("run.failed", {"run_id": run_id, "error": str(exc)})
        except Exception:
            LOGGER.exception("Streaming analysis run failed")
            services.database.finish_run(run_id, "failed", {"error": "internal error"})
            finalized = True
            yield _sse("run.failed", {"run_id": run_id, "error": "Analysis run failed"})
        finally:
            if not finalized:
                services.database.finish_run(run_id, "cancelled", {"error": "Client disconnected"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/api/v1/threads/{thread_id}/memory-proposals",
    response_model=MemoryProposal,
    status_code=status.HTTP_201_CREATED,
)
async def propose_memory(thread_id: str, payload: MemoryProposalCreate, request: Request) -> dict:
    services = _services(request)
    _require_thread(services, thread_id, _session_user_id(request))
    user_id = _scope_user(request, payload.user_id)
    try:
        return services.database.create_memory_proposal(
            thread_id=thread_id,
            user_id=user_id,
            text=payload.text,
            memory_type=payload.memory_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/v1/consents/{consent_id}", response_model=MemoryProposal)
async def decide_consent(consent_id: str, payload: ConsentDecision, request: Request) -> dict:
    services = _services(request)
    existing = services.database.get_consent(consent_id)
    session_user_id = _session_user_id(request)
    if existing is None or (
        session_user_id is not None and existing["user_id"] != session_user_id
    ):
        raise HTTPException(status_code=404, detail="Consent request not found")
    try:
        consent = services.database.decide_consent(consent_id, payload.action, payload.edited_text)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if consent is None:
        raise HTTPException(status_code=404, detail="Consent request not found")
    return consent


@router.get("/api/v1/memories", response_model=list[MemoryRecord])
async def list_memories(
    request: Request, user_id: Annotated[str, Query(min_length=1)]
) -> list[dict]:
    return _services(request).database.list_memories(_scope_user(request, user_id))


@router.delete("/api/v1/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str, request: Request, user_id: Annotated[str, Query(min_length=1)]
) -> None:
    if not _services(request).database.delete_memory(memory_id, _scope_user(request, user_id)):
        raise HTTPException(status_code=404, detail="Memory not found")


@router.delete("/api/v1/privacy/forget-me", response_model=ForgetMeResult)
async def forget_me(request: Request, user_id: Annotated[str, Query(min_length=1)]) -> dict:
    services = _services(request)
    result = services.database.forget_user(_scope_user(request, user_id))
    for stored_path in result.pop("paths"):
        path = Path(stored_path).resolve()
        try:
            path.relative_to(services.settings.upload_dir.resolve())
        except ValueError:
            LOGGER.error("Refused to delete an image outside the controlled upload directory")
            continue
        path.unlink(missing_ok=True)
    return result
