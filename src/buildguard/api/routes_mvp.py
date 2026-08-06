"""Operational MVP API routes backed by local services and SQLite."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

import cv2
import psutil
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from buildguard.config import CameraConfig, CameraPolicyConfig
from buildguard.integration.service import MvpWorkflow
from buildguard.llm.base import LocalLLMBackend
from buildguard.monitoring.dashboard import PerformanceDashboard
from buildguard.realtime.camera_manager import CameraManager
from buildguard.realtime.clip_writer import ensure_browser_compatible_clip
from buildguard.realtime.schemas import QueryRecentEventsInput
from buildguard.storage.database import Database
from buildguard.storage.models import (
    PerformanceLogModel,
    RealtimeEventModel,
    RemediationRecordModel,
    ReportModel,
    SecurityAuditLogModel,
    ToolCallModel,
)
from buildguard.vision.conditional_pipeline import ConditionalInspectionInput


class VerifiedFactRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=100_000)
    source_kind: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    checksum: str | None = Field(default=None, min_length=64, max_length=64)
    confidence: float = Field(default=1.0, ge=0, le=1)


class RemediationRequest(BaseModel):
    action: str = Field(min_length=1, max_length=10_000)
    status: Literal["planned", "in_progress", "completed", "verified", "rejected"]
    actor: str = Field(min_length=1, max_length=256)
    notes: str | None = Field(default=None, max_length=10_000)
    evidence_paths: list[str] = Field(default_factory=list, max_length=100)


class CameraRegistrationRequest(BaseModel):
    camera: CameraConfig
    policy: CameraPolicyConfig | None = None


def create_mvp_router(
    workflow: MvpWorkflow,
    camera_manager: CameraManager,
    database: Database,
    backend: LocalLLMBackend,
    dashboard: PerformanceDashboard,
) -> APIRouter:
    router = APIRouter(tags=["mvp"])

    @router.post("/vision/conditional")
    def conditional_inspection(
        request: ConditionalInspectionInput,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Conditional inspection requires explicit confirmation",
            )
        return (
            workflow.vision.inspect_conditionally(request)
            .to_public_result()
            .model_dump(mode="json")
        )

    @router.get("/sessions")
    def sessions(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return workflow.memory.list_sessions(limit)

    @router.get("/sessions/{session_id}/messages")
    def session_messages(
        session_id: str,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return workflow.memory.list_messages(session_id, limit)

    @router.delete("/sessions/{session_id}")
    def clear_session(session_id: str, confirmed: bool = False) -> dict[str, int]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Clearing session memory requires explicit confirmation",
            )
        return workflow.memory.clear_session(session_id)

    @router.get("/sessions/{session_id}/facts")
    def verified_facts(
        session_id: str,
        active_only: bool = True,
        limit: int = Query(default=500, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return workflow.memory.list_verified_facts(
            session_id,
            active_only=active_only,
            limit=limit,
        )

    @router.post("/sessions/{session_id}/facts")
    def add_verified_fact(
        session_id: str,
        request: VerifiedFactRequest,
    ) -> dict[str, Any]:
        return workflow.memory.add_verified_fact(
            session_id,
            subject=request.subject,
            predicate=request.predicate,
            object_text=request.object,
            source_kind=request.source_kind,
            source_id=request.source_id,
            checksum=request.checksum,
            confidence=request.confidence,
        )

    @router.delete("/sessions/{session_id}/facts/{fact_id}")
    def remove_verified_fact(
        session_id: str,
        fact_id: str,
        confirmed: bool = False,
    ) -> dict[str, bool]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Removing a verified fact requires explicit confirmation",
            )
        removed = workflow.memory.deactivate_verified_fact(session_id, fact_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Verified fact not found")
        return {"deactivated": True}

    @router.get("/tasks")
    def tasks(
        session_id: str | None = None,
        risk: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in workflow.memory.list_tasks(
                session_id=session_id,
                risk=risk,
                limit=limit,
            )
        ]

    @router.get("/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        stored = workflow.memory.get_task(task_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return stored.model_dump(mode="json")

    @router.get("/reports")
    def reports(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return workflow.memory.list_reports(limit)

    @router.get("/reports/{report_id}/download")
    def download_report(
        report_id: str,
        export_format: Literal["md", "html", "pdf"] = Query(default="md", alias="format"),
    ) -> FileResponse:
        with database.session() as session:
            report = session.get(ReportModel, report_id)
            if report is None:
                raise HTTPException(status_code=404, detail="Report not found")
            markdown_path = Path(report.output_path).resolve()
        target = markdown_path.with_suffix(f".{export_format}")
        try:
            target.relative_to(workflow.reports.output_dir)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Report path is outside output root") from exc
        if not target.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"Report format is unavailable: {export_format}",
            )
        media_types = {
            "md": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
            "pdf": "application/pdf",
        }
        return FileResponse(
            target,
            media_type=media_types[export_format],
            filename=target.name,
        )

    @router.get("/events")
    def events(
        camera_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return camera_manager.query_events(
            QueryRecentEventsInput(camera_id=camera_id, limit=limit)
        ).model_dump(mode="json")

    @router.get("/events/{event_id}/clip", response_class=FileResponse)
    def event_clip(event_id: str) -> FileResponse:
        events = camera_manager.query_events(QueryRecentEventsInput(limit=500)).events
        event = next((item for item in events if item.id == event_id), None)
        if event is None:
            raise HTTPException(status_code=404, detail="Realtime event not found")
        if event.clip_path is None:
            raise HTTPException(status_code=404, detail="Event has no video clip")
        source = event.clip_path.resolve()
        if not source.is_file():
            raise HTTPException(status_code=404, detail="Event video clip is no longer available")
        try:
            playable = ensure_browser_compatible_clip(source)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        media_type = "video/webm" if playable.suffix.casefold() == ".webm" else "video/mp4"
        return FileResponse(playable, media_type=media_type)

    @router.post("/events/{event_id}/acknowledge")
    def acknowledge_event(
        event_id: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Acknowledging an event requires explicit confirmation",
            )
        try:
            return camera_manager.acknowledge_event(event_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/events/{event_id}/close")
    def close_event(
        event_id: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Closing an event requires explicit confirmation",
            )
        try:
            return camera_manager.close_event(event_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/events/{event_id}/remediations")
    def remediations(event_id: str) -> list[dict[str, Any]]:
        with database.session() as session:
            rows = session.scalars(
                select(RemediationRecordModel)
                .where(RemediationRecordModel.event_id == event_id)
                .order_by(RemediationRecordModel.created_at.desc())
            ).all()
            return [
                {
                    "id": item.id,
                    "event_id": item.event_id,
                    "action": item.action,
                    "status": item.status,
                    "actor": item.actor,
                    "notes": item.notes,
                    "evidence_paths": item.evidence_json,
                    "created_at": item.created_at.isoformat(),
                }
                for item in rows
            ]

    @router.post("/events/{event_id}/remediations")
    def add_remediation(
        event_id: str,
        request: RemediationRequest,
    ) -> dict[str, Any]:
        with database.session() as session:
            if session.get(RealtimeEventModel, event_id) is None:
                raise HTTPException(status_code=404, detail="Realtime event not found")
            entity = RemediationRecordModel(
                event_id=event_id,
                action=request.action,
                status=request.status,
                actor=request.actor,
                notes=request.notes,
                evidence_json=request.evidence_paths,
            )
            session.add(entity)
            session.flush()
            return {
                "id": entity.id,
                "event_id": entity.event_id,
                "status": entity.status,
            }

    @router.get("/cameras")
    def cameras() -> dict[str, Any]:
        return camera_manager.list_status(include_stopped=True).model_dump(mode="json")

    @router.post("/cameras")
    def register_camera(
        request: CameraRegistrationRequest,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Registering a camera requires explicit confirmation",
            )
        try:
            return camera_manager.register(
                request.camera,
                request.policy,
            ).model_dump(mode="json")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/cameras/{camera_id}")
    def unregister_camera(camera_id: str, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Removing a camera requires explicit confirmation",
            )
        try:
            return camera_manager.unregister(camera_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put("/cameras/{camera_id}/policy")
    def update_camera_policy(
        camera_id: str,
        policy: CameraPolicyConfig,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Updating camera policy requires explicit confirmation",
            )
        try:
            return camera_manager.update_policy(camera_id, policy).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/cameras/{camera_id}/snapshot")
    def camera_snapshot(camera_id: str) -> Response:
        try:
            frame = camera_manager.latest_frame(camera_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if frame is None:
            raise HTTPException(status_code=404, detail="No camera frame is available")
        ok, encoded = cv2.imencode(".jpg", frame.image)
        if not ok:
            raise HTTPException(status_code=500, detail="Could not encode camera frame")
        return Response(content=encoded.tobytes(), media_type="image/jpeg")

    @router.get("/cameras/{camera_id}/stream.mjpg")
    def camera_stream(camera_id: str) -> StreamingResponse:
        def generate() -> Any:
            while True:
                frame = camera_manager.latest_frame(camera_id)
                if frame is None:
                    time.sleep(0.2)
                    continue
                ok, encoded = cv2.imencode(".jpg", frame.image)
                if ok:
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
                    )
                time.sleep(0.2)

        if camera_id not in camera_manager.camera_configs:
            raise HTTPException(status_code=404, detail="Camera not found")
        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @router.post("/cameras/{camera_id}/start")
    def start_camera(camera_id: str, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Starting camera monitoring requires explicit confirmation",
            )
        try:
            return camera_manager.start(camera_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/cameras/{camera_id}/stop")
    def stop_camera(camera_id: str, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise HTTPException(
                status_code=409,
                detail="Stopping camera monitoring requires explicit confirmation",
            )
        try:
            return camera_manager.stop(camera_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runtime/metrics")
    def runtime_metrics(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        process = psutil.Process()
        with database.session() as session:
            rows = session.scalars(
                select(PerformanceLogModel)
                .order_by(PerformanceLogModel.created_at.desc())
                .limit(limit)
            ).all()
        metrics_history = getattr(backend, "metrics_history", [])
        llm = [item.model_dump(mode="json") for item in metrics_history[-limit:]]
        operations = [
            {
                "operation": item.operation,
                "duration_ms": item.duration_ms,
                "success": item.success,
                "metrics": item.metrics_json,
                "created_at": item.created_at.isoformat(),
            }
            for item in rows
        ]
        dashboard_payload = dashboard.payload(
            llm_metrics=llm,
            operations=operations,
            limit=limit,
        )
        return {
            "process": {
                "pid": process.pid,
                "rss_bytes": process.memory_info().rss,
                "cpu_percent": process.cpu_percent(interval=None),
            },
            "llm": llm,
            "operations": operations,
            **dashboard_payload,
        }

    @router.get("/runtime/export")
    def runtime_export(
        export_format: Literal["json", "csv", "chart"] = Query(
            default="json",
            alias="format",
        ),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> Response:
        payload = runtime_metrics(limit)
        content, media_type, filename = dashboard.export(payload, export_format)
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @router.get("/audit")
    def audit(
        actor: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        with database.session() as session:
            statement = select(SecurityAuditLogModel)
            if actor is not None:
                statement = statement.where(SecurityAuditLogModel.actor == actor)
            if action is not None:
                statement = statement.where(SecurityAuditLogModel.action == action)
            if outcome is not None:
                statement = statement.where(SecurityAuditLogModel.outcome == outcome)
            rows = session.scalars(
                statement.order_by(SecurityAuditLogModel.created_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": item.id,
                    "actor": item.actor,
                    "action": item.action,
                    "resource": item.resource,
                    "outcome": item.outcome,
                    "details": item.details_json,
                    "created_at": item.created_at.isoformat(),
                }
                for item in rows
            ]

    @router.get("/tool-calls")
    def tool_calls(
        task_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        with database.session() as session:
            statement = select(ToolCallModel)
            if task_id is not None:
                statement = statement.where(ToolCallModel.task_id == task_id)
            rows = session.scalars(
                statement.order_by(ToolCallModel.created_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": item.id,
                    "task_id": item.task_id,
                    "tool_name": item.tool_name,
                    "arguments": item.arguments_json,
                    "result": item.result_json,
                    "success": item.success,
                    "duration_ms": item.duration_ms,
                    "created_at": item.created_at.isoformat(),
                }
                for item in rows
            ]

    return router
