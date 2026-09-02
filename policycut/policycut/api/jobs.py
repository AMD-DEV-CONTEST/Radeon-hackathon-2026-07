"""Job endpoints: start analysis/render jobs, poll, cancel, SSE progress."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from policycut.core.ids import new_id
from policycut.core.models import Job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

TERMINAL_STATUSES = {"done", "error", "cancelled", "server_restarted"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(request: Request):
    return request.app.state.store


def _queue(request: Request):
    return request.app.state.queue


def _settings(request: Request):
    return request.app.state.settings


def _get_project_or_404(store, project_id: str):
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


def _project_busy(store, project_id: str) -> bool:
    try:
        jobs = store.load_jobs(project_id) or []
    except Exception:
        return False
    return any(j.status in ("queued", "running") for j in jobs)


def _queue_cancel_event(queue, job_id: str):
    """Best-effort lookup of the queue's cancel event for a job."""
    for attr in ("get_cancel_event", "cancel_event_for", "cancel_event"):
        fn = getattr(queue, attr, None)
        if callable(fn):
            try:
                event = fn(job_id)
                if event is not None:
                    return event
            except Exception:
                continue
    events = getattr(queue, "cancel_events", None)
    if isinstance(events, dict):
        return events.get(job_id)
    return None


def _make_job(project_id: str, job_type: str) -> Job:
    return Job(
        id=new_id("j"),
        project_id=project_id,
        type=job_type,
        status="queued",
        created_at=_utcnow(),
    )


def _pipeline_fn(job_type: str, project_id: str, store, settings, queue, job_id: str):
    """Build the queue worker function; imports the pipeline lazily."""

    def _run(job, progress_cb, cancel_event=None, *args, **kwargs):
        from policycut import pipeline  # lazy import keeps API startup light

        event = cancel_event or _queue_cancel_event(queue, job_id) or threading.Event()
        if job_type == "analysis":
            pipeline.run_analysis(project_id, store, settings, progress_cb, event)
        else:
            pipeline.run_render(project_id, store, settings, progress_cb, event)

    return _run


@router.post("/projects/{project_id}/jobs/analysis")
def start_analysis(project_id: str, request: Request):
    store = _store(request)
    queue = _queue(request)
    settings = _settings(request)
    project = _get_project_or_404(store, project_id)
    if _project_busy(store, project_id):
        raise HTTPException(
            status_code=409, detail="A job is already queued or running for this project"
        )
    if project.media is None:
        raise HTTPException(status_code=400, detail="Upload a video before starting analysis")
    if store.load_policy(project_id) is None:
        raise HTTPException(status_code=400, detail="Save a policy before starting analysis")

    job = _make_job(project_id, "analysis")
    store.save_job(job)
    project.status = "analyzing"
    project.error = None
    project.updated_at = _utcnow()
    store.save_project(project)
    queue.submit(job, _pipeline_fn("analysis", project_id, store, settings, queue, job.id))
    return job


@router.post("/projects/{project_id}/jobs/render")
def start_render(project_id: str, request: Request):
    store = _store(request)
    queue = _queue(request)
    settings = _settings(request)
    project = _get_project_or_404(store, project_id)
    if _project_busy(store, project_id):
        raise HTTPException(
            status_code=409, detail="A job is already queued or running for this project"
        )
    events = store.load_events(project_id) or []
    pending_auto = [e for e in events if e.source == "auto" and e.status == "pending"]
    if pending_auto:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(pending_auto)} auto-detected events are still pending review; "
                "confirm or ignore them before rendering"
            ),
        )

    job = _make_job(project_id, "render")
    store.save_job(job)
    project.status = "rendering"
    project.error = None
    project.updated_at = _utcnow()
    store.save_project(project)
    queue.submit(job, _pipeline_fn("render", project_id, store, settings, queue, job.id))
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    job = _store(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    store = _store(request)
    queue = _queue(request)
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    if job.status not in TERMINAL_STATUSES:
        cancel = getattr(queue, "cancel", None)
        if callable(cancel):
            try:
                cancel(job_id)
            except Exception:
                logger.exception("queue.cancel failed for %s", job_id)
    return store.get_job(job_id) or job


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    """SSE stream of job progress; polls the store every 0.5s, emits on change."""
    store = _store(request)
    if store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    async def _generate():
        yield "retry: 2000\n\n"  # client reconnect hint
        last_payload = None
        while True:
            try:
                if await request.is_disconnected():
                    break
            except Exception:
                pass
            job = store.get_job(job_id)
            if job is None:
                yield "event: done\ndata: {}\n\n"
                break
            payload = job.model_dump_json()
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
            if job.status in TERMINAL_STATUSES:
                yield f"event: done\ndata: {payload}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
