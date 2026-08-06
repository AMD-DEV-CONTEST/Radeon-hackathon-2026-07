"""Production Agent tools backed by validated and audited local services."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2

from pydantic import Field, model_validator

from buildguard.agent.nodes.executor import Tool
from buildguard.config import PermissionConfig
from buildguard.integration.service import MvpChatInput, MvpWorkflow
from buildguard.logging_system.jsonl_writer import JsonlWriter, redact
from buildguard.rag.advanced.corrective_retriever import AdvancedRagPipeline
from buildguard.rag.schemas import RagSearchInput, RagSearchOutput
from buildguard.rag.service import RagService
from buildguard.rag.tool import register_rag_tool
from buildguard.realtime.camera_manager import CameraManager, register_realtime_tools
from buildguard.risk.service import RiskAssessmentService, register_risk_tool
from buildguard.schemas.common import StrictSchema
from buildguard.schemas.tools import ToolCallResult
from buildguard.schemas.vision import InspectionResult
from buildguard.security.advanced.capabilities import CapabilityManager
from buildguard.security.advanced.trust_labels import (
    LabeledData,
    Provenance,
    TrustLabel,
)
from buildguard.security.audit import ToolAuditLogger
from buildguard.security.confirmation import ConfirmationManager
from buildguard.security.path_guard import PathGuard
from buildguard.security.permission_engine import CONFIRMATION_OPERATIONS, PermissionEngine
from buildguard.storage.memory import LongTermMemory
from buildguard.tools.base import ToolDefinition
from buildguard.tools.builtin.file_tools import register_file_tools
from buildguard.tools.builtin.history_tools import register_history_tools
from buildguard.tools.executor import ToolExecutor
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import ToolExecutionRequest
from buildguard.vision.schemas import SingleImageInspectionInput, SingleImageInspectionOutput
from buildguard.vision.service import VisionInspectionService, register_vision_tools

LOGGER = logging.getLogger(__name__)


class EchoInput(StrictSchema):
    text: str = Field(default="", max_length=100_000)


class EchoOutput(StrictSchema):
    text: str


class LegacyInspectInput(StrictSchema):
    image_path: Path | None = None
    path: Path | None = None
    text: str | None = None

    @model_validator(mode="after")
    def require_path(self) -> LegacyInspectInput:
        if self.image_path is None and self.path is None and not (self.text or "").strip():
            raise ValueError("inspect_image requires image_path")
        return self


class LegacySearchInput(StrictSchema):
    query: str | None = Field(default=None, max_length=10_000)
    text: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def require_query(self) -> LegacySearchInput:
        if not (self.query or self.text or "").strip():
            raise ValueError("search_memory requires a non-empty query")
        return self


class InspectVideoInput(StrictSchema):
    video_path: Path
    sample_interval_seconds: float = Field(default=2.0, gt=0, le=60)
    max_frames: int = Field(default=10, ge=1, le=30)


class FrameInspectionResult(StrictSchema):
    frame_index: int
    timestamp_seconds: float
    inspection: InspectionResult


class VideoInspectionOutput(StrictSchema):
    video_path: Path
    total_frames_sampled: int
    duration_seconds: float
    frame_results: list[FrameInspectionResult]
    all_labels: list[str]
    max_severity: str | None
    summary: str


class GenerateInspectionReportInput(StrictSchema):
    """Identify the persisted session whose latest inspection is reported."""

    session_id: str = Field(min_length=1, max_length=128)
    filename: str | None = Field(default=None, min_length=1, max_length=120)


class GenerateInspectionReportOutput(StrictSchema):
    task_id: str
    report_path: Path
    html_path: Path
    pdf_path: Path | None = None
    verified_citation_count: int = Field(ge=0)


class GenerateEventReportInput(StrictSchema):
    session_id: str = Field(min_length=1, max_length=128)


class GenerateEventReportOutput(StrictSchema):
    task_id: str
    event_ids: list[str] = Field(default_factory=list)
    report_id: str
    report_path: Path
    html_path: Path
    pdf_path: Path | None = None


def _bridge_registry(registry: ToolRegistry) -> dict[str, Tool]:
    """Keep direct callable compatibility for tests and trusted local callers."""
    tools: dict[str, Tool] = {}
    for metadata in registry.export_metadata():
        name = str(metadata["name"])
        registered = registry.get(name)

        def invoke(
            arguments: dict[str, Any],
            *,
            definition: ToolDefinition = registered.definition,
            handler: Any = registered.handler,
        ) -> dict[str, Any]:
            request = definition.input_schema.model_validate(arguments)
            raw_output = handler(request)
            output = definition.output_schema.model_validate(raw_output)
            return output.model_dump(mode="json")

        tools[name] = invoke
    return tools


class AgentToolCatalog(dict[str, Tool]):
    """Mapping-compatible catalog with one secure execution boundary."""

    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        confirmations: ConfirmationManager,
        capabilities: CapabilityManager,
        *,
        workspace_root: Path,
        capability_ttl_seconds: int,
        capability_max_uses: int,
        memory: LongTermMemory | None,
    ) -> None:
        super().__init__(_bridge_registry(registry))
        self.registry = registry
        self.executor = executor
        self.confirmations = confirmations
        self.capabilities = capabilities
        self.workspace_root = workspace_root.resolve()
        self.capability_ttl_seconds = capability_ttl_seconds
        self.capability_max_uses = capability_max_uses
        self.memory = memory

    def planner_metadata(self) -> list[dict[str, Any]]:
        return self.registry.export_metadata()

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        confirmed: bool,
    ) -> ToolCallResult:
        registered = self.registry.get(tool_name)
        definition = registered.definition
        confirmation_id: str | None = None
        needs_confirmation = (
            definition.permission == "confirm"
            or definition.name in CONFIRMATION_OPERATIONS
            or (definition.name == "list_inspection_images" and bool(arguments.get("recursive")))
        )
        if confirmed and needs_confirmation:
            confirmation = self.confirmations.create(
                definition.name,
                arguments,
                definition.allowed_roots,
                "The user approved this bounded Agent plan operation.",
            )
            self.confirmations.decide(confirmation.id, True)
            confirmation_id = confirmation.id

        root = definition.allowed_roots[0] if definition.allowed_roots else self.workspace_root
        capability = self.capabilities.issue(
            task_id=task_id,
            tool_name=definition.name,
            root=root,
            operations=["read" if definition.read_only else "write"],
            resource_ids=[],
            ttl_seconds=self.capability_ttl_seconds,
            max_uses=self.capability_max_uses,
            issued_by=LabeledData(
                value="agent-tool-policy",
                label=TrustLabel.TRUSTED_POLICY,
                provenance=Provenance(
                    source_id="buildguard-agent-tool-catalog",
                    source_kind="static_policy",
                ),
            ),
        )
        result = self.executor.execute(
            ToolExecutionRequest(
                session_id=session_id,
                task_id=task_id,
                actor="buildguard-agent",
                tool_name=tool_name,
                arguments=arguments,
                confirmation_id=confirmation_id,
                capability_id=capability.capability_id,
            )
        )
        if self.memory is not None:
            try:
                self.memory.record_tool_call(
                    task_id,
                    tool_name,
                    redact(arguments),
                    result=redact(result.output) if result.output is not None else None,
                    success=result.success,
                    duration_ms=result.duration_ms,
                )
            except Exception as exc:  # noqa: BLE001 - persistence is best effort
                # Tool execution and its append-only audit remain authoritative even
                # when optional queryable persistence is temporarily unavailable.
                LOGGER.warning("Tool-call persistence failed: %s", exc)
        return result


def _register_compatibility_tools(
    registry: ToolRegistry,
    vision: VisionInspectionService,
    rag: RagService,
    *,
    advanced_rag: AdvancedRagPipeline | None,
    timeout_seconds: float,
    video_roots: list[Path] | None = None,
) -> None:
    registry.register(
        ToolDefinition(
            name="echo",
            description="Return bounded text unchanged for local Agent diagnostics.",
            input_schema=EchoInput,
            output_schema=EchoOutput,
            permission="auto",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="utility",
        ),
        lambda raw: EchoOutput(text=EchoInput.model_validate(raw).text),
    )

    def inspect(raw: object) -> SingleImageInspectionOutput:
        request = LegacyInspectInput.model_validate(raw)
        image_path = request.image_path or request.path or Path(request.text or "")
        return vision.inspect_single(SingleImageInspectionInput(image_path=image_path))

    registry.register(
        ToolDefinition(
            name="inspect_image",
            description="Compatibility alias for one schema-validated image inspection.",
            input_schema=LegacyInspectInput,
            output_schema=SingleImageInspectionOutput,
            permission="confirm",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="vision",
            allowed_roots=[path.resolve() for path in vision.config.allowed_image_roots],
            allowed_extensions=[".jpg", ".jpeg", ".png"],
        ),
        inspect,
    )

    uploads_root = vision.config.allowed_image_roots[0].resolve() if vision.config.allowed_image_roots else Path("workspace/uploads").resolve()
    effective_video_roots = video_roots if video_roots else [uploads_root]
    video_path_guard = PathGuard(effective_video_roots)

    def inspect_video(raw: object) -> VideoInspectionOutput:
        request = InspectVideoInput.model_validate(raw)
        source = video_path_guard.resolve_read(request.video_path)
        if source.suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv"}:
            raise ValueError(f"Unsupported video extension: {source.suffix}")
        cap = cv2.VideoCapture(str(source))
        frame_results: list[FrameInspectionResult] = []
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 1.0
            total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            duration_seconds = total_frames / fps if fps > 0 else 0.0
            step = max(1, int(fps * request.sample_interval_seconds))
            cap_limit = min(request.max_frames, 30)
            frame_index = 0
            sampled = 0
            while sampled < cap_limit:
                cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index))
                ok, bgr = cap.read()
                if not ok:
                    break
                tmp = uploads_root / f".video_frame_{uuid4().hex}.jpg"
                try:
                    ok2, encoded = cv2.imencode(".jpg", bgr)
                    if not ok2:
                        frame_index += step
                        continue
                    tmp.write_bytes(encoded.tobytes())
                    result = vision.inspect_single(
                        SingleImageInspectionInput(image_path=tmp)
                    )
                    frame_results.append(
                        FrameInspectionResult(
                            frame_index=frame_index,
                            timestamp_seconds=frame_index / fps,
                            inspection=result.inspection,
                        )
                    )
                finally:
                    tmp.unlink(missing_ok=True)
                frame_index += step
                sampled += 1
        finally:
            cap.release()

        all_labels = sorted({
            d.label
            for fr in frame_results
            for d in fr.inspection.detections
        })
        # max_severity: derive from RiskAssessment.severity on each frame's detections.
        # If any frame has risk assessments, use the highest severity string; if
        # detections exist but no risk assessments yet, use "normal"; otherwise None.
        all_severities = [
            ra.severity.value if hasattr(ra.severity, "value") else str(ra.severity)
            for fr in frame_results
            for ra in fr.inspection.risks
        ]
        severity_rank = {"low": 0, "normal": 1, "high": 2, "critical": 3}
        has_detections = any(fr.inspection.detections for fr in frame_results)
        max_severity: str | None = None
        if all_severities:
            max_severity = max(all_severities, key=lambda s: severity_rank.get(s.lower(), 0))
        elif has_detections:
            max_severity = "normal"

        n = len(frame_results)
        if all_labels:
            label_counts = {
                lbl: sum(
                    1 for fr in frame_results
                    if any(d.label == lbl for d in fr.inspection.detections)
                )
                for lbl in all_labels
            }
            parts = ", ".join(f"{lbl} ({cnt} frames)" for lbl, cnt in label_counts.items())
            summary = f"{n} frames sampled over {duration_seconds:.1f}s; found: {parts}"
        else:
            summary = f"{n} frames sampled over {duration_seconds:.1f}s; no safety violations detected"

        return VideoInspectionOutput(
            video_path=request.video_path,
            total_frames_sampled=n,
            duration_seconds=duration_seconds,
            frame_results=frame_results,
            all_labels=all_labels,
            max_severity=max_severity,
            summary=summary,
        )

    def search(raw: object) -> RagSearchOutput:
        request = LegacySearchInput.model_validate(raw)
        rag_request = RagSearchInput(query=(request.query or request.text or ""))
        if advanced_rag is None:
            return rag.search(rag_request)
        result = advanced_rag.retrieve(rag_request)
        return RagSearchOutput(
            chunks=result.chunks,
            retrieved_chunk_ids=[item.chunk_id for item in result.chunks],
            reranked_chunk_ids=[item.chunk_id for item in result.chunks],
            scores=result.scores,
            citations=result.citations,
            evidence_status=(
                "sufficient" if result.evidence_status == "sufficient" else "insufficient_evidence"
            ),
            retrieval_latency_ms=result.retrieval_latency_ms,
            stage_latency_ms={"advanced_rag": result.retrieval_latency_ms},
        )

    registry.register(
        ToolDefinition(
            name="search_memory",
            description="Compatibility alias for local construction knowledge retrieval.",
            input_schema=LegacySearchInput,
            output_schema=RagSearchOutput,
            permission="auto",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="rag",
        ),
        search,
    )

    registry.register(
        ToolDefinition(
            name="inspect_video",
            description=(
                "Sample frames from a local video file and inspect each for safety violations. "
                "Returns per-frame detections and an aggregated summary."
            ),
            input_schema=InspectVideoInput,
            output_schema=VideoInspectionOutput,
            permission="confirm",
            read_only=True,
            timeout_seconds=120,
            category="vision",
            allowed_roots=effective_video_roots,
            allowed_extensions=[".mp4", ".avi", ".mov", ".mkv"],
        ),
        inspect_video,
    )


def create_production_agent_tools(
    vision: VisionInspectionService,
    rag: RagService,
    *,
    risk: RiskAssessmentService | None = None,
    memory: LongTermMemory | None = None,
    camera_manager: CameraManager | None = None,
    workflow: MvpWorkflow | None = None,
    advanced_rag: AdvancedRagPipeline | None = None,
    permissions: PermissionConfig | None = None,
    workspace_root: Path | None = None,
    inspection_image_max_items: int = 100,
    timeout_seconds: float = 30,
) -> AgentToolCatalog:
    """Bind canonical Agent tools to schema, permission and audit controls."""

    policy = permissions or PermissionConfig()
    root = (workspace_root or Path("workspace")).resolve()
    registry = ToolRegistry()
    register_vision_tools(registry, vision, timeout_seconds=timeout_seconds)
    register_rag_tool(
        registry,
        rag,
        advanced=advanced_rag,
        timeout_seconds=timeout_seconds,
    )
    roots = [path.resolve() for path in vision.config.allowed_image_roots]
    if roots:
        register_file_tools(
            registry,
            PathGuard(roots),
            roots[0],
            max_items=inspection_image_max_items,
            timeout_seconds=timeout_seconds,
        )
    if risk is not None:
        register_risk_tool(registry, risk, timeout_seconds=timeout_seconds)
    if memory is not None:
        register_history_tools(
            registry,
            lambda session_id, limit: [
                item.model_dump(mode="json")
                for item in memory.list_tasks(session_id=session_id, limit=limit)
            ],
            timeout_seconds=timeout_seconds,
        )
    if camera_manager is not None:
        register_realtime_tools(registry, camera_manager, timeout_seconds=timeout_seconds)
    _register_compatibility_tools(
        registry,
        vision,
        rag,
        advanced_rag=advanced_rag,
        timeout_seconds=timeout_seconds,
        video_roots=[root.parent],
    )

    if workflow is not None:

        def generate_report(raw: object) -> GenerateInspectionReportOutput:
            request = GenerateInspectionReportInput.model_validate(raw)
            artifact = workflow.export_latest_report(
                request.session_id,
                filename=request.filename,
                confirmed=True,
            )
            return GenerateInspectionReportOutput(
                task_id=artifact["task_id"],
                report_path=artifact["report_path"],
                html_path=artifact["html_path"],
                pdf_path=artifact.get("pdf_path"),
                verified_citation_count=artifact["verified_citation_count"],
            )

        registry.register(
            ToolDefinition(
                name="generate_inspection_report",
                description="Generate verified Markdown and HTML from persisted inspection data.",
                input_schema=GenerateInspectionReportInput,
                output_schema=GenerateInspectionReportOutput,
                permission="confirm",
                read_only=False,
                timeout_seconds=timeout_seconds,
                category="reporting",
                allowed_roots=[root],
            ),
            generate_report,
        )

        def generate_event_report(raw: object) -> GenerateEventReportOutput:
            request = GenerateEventReportInput.model_validate(raw)
            pending = workflow.chat(
                MvpChatInput(
                    message="Agent requested a report for current realtime events.",
                    session_id=request.session_id,
                    action="event_report",
                )
            )
            artifact = workflow.confirm(str(pending["task_id"]), True)
            return GenerateEventReportOutput(
                task_id=str(artifact["task_id"]),
                event_ids=[str(item) for item in artifact.get("event_ids", [])],
                report_id=str(artifact["report_id"]),
                report_path=Path(str(artifact["report_path"])),
                html_path=Path(str(artifact["html_path"])),
                pdf_path=(
                    Path(str(artifact["pdf"]["path"]))
                    if isinstance(artifact.get("pdf"), dict)
                    and artifact["pdf"].get("available")
                    and artifact["pdf"].get("path")
                    else None
                ),
            )

        registry.register(
            ToolDefinition(
                name="generate_event_report",
                description="Generate a verified report from current realtime risk events.",
                input_schema=GenerateEventReportInput,
                output_schema=GenerateEventReportOutput,
                permission="confirm",
                read_only=False,
                timeout_seconds=timeout_seconds,
                category="reporting",
                allowed_roots=[root],
            ),
            generate_event_report,
        )

    confirmations = ConfirmationManager(policy.confirmation_ttl_seconds)
    capability_manager = CapabilityManager(
        max_ttl_seconds=policy.advanced.capability_ttl_seconds,
        default_max_uses=policy.advanced.capability_max_uses,
    )
    audit_writer = JsonlWriter(root / "logs" / "audit" / "agent-tools.jsonl")
    audit_logger = ToolAuditLogger(
        audit_writer,
        memory.record_tool_audit if memory is not None else None,
    )
    executor = ToolExecutor(
        registry,
        PermissionEngine(confirmations),
        audit_logger,
        retry_attempts=policy.tool_retry_attempts,
        retry_wait_seconds=policy.tool_retry_wait_seconds,
        capability_manager=capability_manager,
        require_capability=(policy.advanced.enabled and policy.advanced.require_capabilities),
    )
    return AgentToolCatalog(
        registry,
        executor,
        confirmations,
        capability_manager,
        workspace_root=root,
        capability_ttl_seconds=policy.advanced.capability_ttl_seconds,
        capability_max_uses=policy.advanced.capability_max_uses,
        memory=memory,
    )
