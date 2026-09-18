"""Persistent MVP workflows without repeated visual inference."""

from __future__ import annotations

import time
from uuid import NAMESPACE_URL, uuid5
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from buildguard.rag.advanced.corrective_retriever import AdvancedRagPipeline
from buildguard.rag.schemas import DocumentChunk, RagSearchInput
from buildguard.rag.service import RagService
from buildguard.realtime.schemas import RealtimeRiskEvent
from buildguard.reporting.builder import (
    ReportBuilder,
    ReportDraft,
    ReportEvidence,
    ReportInput,
)
from buildguard.reporting.citation_validator import CitationStatement
from buildguard.risk.service import RiskAssessmentService
from buildguard.schemas.common import Severity, StrictSchema
from buildguard.schemas.rag import RetrievedEvidence
from buildguard.schemas.vision import Detection, InspectionResult, RiskAssessment
from buildguard.storage.memory import LongTermMemory, StoredTask
from buildguard.vision.schemas import BatchImageInspectionInput, SingleImageInspectionInput
from buildguard.vision.service import VisionInspectionService

RiskName = Literal["info", "low", "normal", "medium", "high", "critical"]
RISK_ORDER: dict[str, int] = {
    "info": 0,
    "low": 1,
    "normal": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
}


class MvpChatInput(StrictSchema):
    message: str = Field(min_length=1, max_length=100_000)
    session_id: str | None = Field(default=None, max_length=128)
    action: Literal["inspect", "high_risk", "report", "history", "event_report"] | None = None
    image_paths: list[Path] = Field(default_factory=list, max_length=1000)
    project_id: str | None = Field(default=None, max_length=128)
    construction_stage: str | None = Field(default=None, max_length=128)
    zone_risk: float | None = Field(default=None, ge=0, le=1)
    task_id: str | None = Field(default=None, max_length=128, exclude=True)


class MvpWorkflow:
    """Join deterministic services and make long-term reuse observable."""

    def __init__(
        self,
        memory: LongTermMemory,
        vision: VisionInspectionService,
        rag: RagService,
        risk: RiskAssessmentService,
        reports: ReportBuilder,
        event_provider: Callable[[], list[RealtimeRiskEvent]] | None = None,
        advanced_rag: AdvancedRagPipeline | None = None,
    ) -> None:
        self.memory = memory
        self.vision = vision
        self.rag = rag
        self.risk = risk
        self.reports = reports
        self.event_provider = event_provider
        self.advanced_rag = advanced_rag
        self.vision_inference_count = 0

    def has_session(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        return any(
            "agent_state" not in task.result
            for task in self.memory.list_tasks(session_id=session_id, limit=20)
        )

    @staticmethod
    def _infer_action(request: MvpChatInput) -> str:
        if request.action is not None:
            return request.action
        text = request.message.casefold()
        if request.image_paths:
            return "inspect"
        if "报告" in text or "report" in text:
            return "report"
        if "高风险" in text or "high risk" in text or "critical" in text:
            return "high_risk"
        return "history"

    @staticmethod
    def _max_risk(risks: list[RiskAssessment]) -> str:
        return max(
            (item.severity.value for item in risks),
            key=lambda item: RISK_ORDER[item],
            default=Severity.LOW.value,
        )

    @staticmethod
    def _retrieved_evidence(
        chunks: list[DocumentChunk], scores: list[float]
    ) -> list[RetrievedEvidence]:
        return [
            RetrievedEvidence(
                document_id=chunk.document_checksum,
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                score=max(0.0, min(1.0, score)),
                source=str(chunk.source_path),
                metadata={
                    key: value
                    for key, value in {
                        "document_name": chunk.document_name,
                        "page": chunk.page,
                        "article": chunk.article,
                    }.items()
                    if isinstance(value, (str, int, float, bool))
                },
            )
            for chunk, score in zip(chunks, scores, strict=True)
        ]

    def _search_for_inspection(
        self,
        inspection: InspectionResult,
    ) -> tuple[list[DocumentChunk], list[float], str, float, dict[str, float]]:
        labels = sorted({item.label for item in inspection.detections})
        if not labels:
            return [], [], "insufficient_evidence", 0.0, {}
        rag_request = RagSearchInput(
            query="施工安全规范 " + " ".join(labels),
            top_k=5,
        )
        if self.advanced_rag is not None:
            advanced = self.advanced_rag.retrieve(rag_request)
            return (
                advanced.chunks,
                advanced.scores,
                advanced.evidence_status,
                advanced.retrieval_latency_ms,
                {
                    "advanced_rag": advanced.retrieval_latency_ms,
                    "retrieval_attempts": float(advanced.retrieval_attempts),
                    "correction_count": float(advanced.correction_count),
                },
            )
        result = self.rag.search(rag_request)
        return (
            result.chunks,
            result.scores,
            result.evidence_status,
            result.retrieval_latency_ms,
            result.stage_latency_ms,
        )

    def _inspect(self, request: MvpChatInput, session_id: str) -> dict[str, Any]:
        if not request.image_paths:
            raise ValueError("inspect action requires at least one image_path")
        task = self.memory.create_task(
            session_id,
            "施工图片巡检",
            request.message,
            task_id=request.task_id,
        )
        started = time.perf_counter()
        inspections: list[InspectionResult] = []
        all_risks: list[RiskAssessment] = []
        all_chunks: dict[str, DocumentChunk] = {}
        evidence_statuses: list[str] = []
        reused_count = 0
        tool_chain: list[str] = []
        failures: list[dict[str, str]] = []
        visual_evidence: list[ReportEvidence] = []
        pending_sources: list[Path] = []
        for source in request.image_paths:
            resolved = str(source.resolve())
            cached = self.memory.find_inspection(session_id, resolved)
            if cached is not None:
                inspection, cached_risks = cached
                inspections.append(inspection)
                all_risks.extend(cached_risks)
                reused_count += 1
                continue
            pending_sources.append(source)

        outputs = []
        if len(pending_sources) > 1:
            try:
                batch = self.vision.inspect_batch(
                    BatchImageInspectionInput(
                        image_paths=pending_sources,
                        max_items=len(pending_sources),
                    )
                )
                outputs.extend(batch.results)
                failures.extend(
                    {
                        "source_path": str(item.image_path),
                        "error": item.error,
                    }
                    for item in batch.failures
                )
                tool_chain.append("inspect_image_batch")
            except Exception as exc:
                failures.extend(
                    {"source_path": str(source), "error": str(exc)} for source in pending_sources
                )
        elif pending_sources:
            try:
                outputs.append(
                    self.vision.inspect_single(
                        SingleImageInspectionInput(image_path=pending_sources[0])
                    )
                )
                tool_chain.append("inspect_single_image")
            except Exception as exc:
                failures.append({"source_path": str(pending_sources[0]), "error": str(exc)})

        for output in outputs:
            try:
                self.memory.record_performance(
                    "vision_inference",
                    output.inspection.processing_ms,
                    metrics={
                        "task_id": task.id,
                        "source": str(output.inspection.source_path),
                        "model": output.inspection.model_name,
                        "rgc_before_calls": sum(
                            len(item.candidate_model_names)
                            for item in output.summary.routing_decisions
                        ),
                        "rgc_after_calls": sum(
                            len(item.selected_model_names)
                            for item in output.summary.routing_decisions
                        ),
                    },
                )
                self.vision_inference_count += 1
                detections = [
                    detection.model_copy(
                        update={
                            "attributes": {
                                **detection.attributes,
                                "repeat_count": max(
                                    int(detection.attributes.get("repeat_count", 0)),
                                    self.memory.count_detection_occurrences(
                                        session_id,
                                        detection.label,
                                    )
                                    + 1,
                                ),
                                **(
                                    {"project_id": request.project_id} if request.project_id else {}
                                ),
                                **(
                                    {"construction_stage": request.construction_stage}
                                    if request.construction_stage
                                    else {}
                                ),
                                **(
                                    {"zone_risk": request.zone_risk}
                                    if request.zone_risk is not None
                                    else {}
                                ),
                            }
                        }
                    )
                    for detection in output.inspection.detections
                ]
                contextual_inspection = output.inspection.model_copy(
                    update={"detections": detections}
                )
                (
                    chunks,
                    scores,
                    evidence_status,
                    retrieval_latency_ms,
                    rag_stages,
                ) = self._search_for_inspection(contextual_inspection)
                self.memory.record_performance(
                    "rag_retrieval",
                    retrieval_latency_ms,
                    metrics={"task_id": task.id, **rag_stages},
                )
                if "reranker" in rag_stages:
                    self.memory.record_performance(
                        "reranker",
                        rag_stages["reranker"],
                        metrics={"task_id": task.id},
                    )
                tool_chain.append("search_construction_standards")
                evidence_statuses.append(evidence_status)
                evidence = self._retrieved_evidence(chunks, scores)
                risk_started = time.perf_counter()
                assessment = self.risk.assess(
                    contextual_inspection,
                    evidence,
                ).assessment
                self.memory.record_performance(
                    "risk_assessment",
                    (time.perf_counter() - risk_started) * 1000,
                    metrics={"task_id": task.id},
                )
                tool_chain.append("assess_risk")
                inspection = contextual_inspection.model_copy(update={"risks": [assessment]})
                visual_evidence.extend(
                    ReportEvidence(
                        source_path=item.image_path,
                        visualization_path=item.visualization_path,
                        label=str(item.metadata.get("label", "unknown")),
                        confidence=item.confidence,
                        bounding_box=item.bbox,
                        source_model=item.source_model,
                    )
                    for item in output.evidence
                )
                inspections.append(inspection)
                all_risks.append(assessment)
                all_chunks.update({chunk.chunk_id: chunk for chunk in chunks})
                self.memory.save_inspection(session_id, inspection, [assessment])
            except Exception as exc:
                failures.append(
                    {
                        "source_path": str(output.inspection.source_path),
                        "error": str(exc),
                    }
                )
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.memory.record_performance(
            "end_to_end_inspection",
            elapsed_ms,
            success=bool(inspections),
            metrics={
                "task_id": task.id,
                "image_count": len(request.image_paths),
                "failure_count": len(failures),
            },
        )
        result: dict[str, Any] = {
            "action": "inspect",
            "inspections": [item.model_dump(mode="json") for item in inspections],
            "risks": [item.model_dump(mode="json") for item in all_risks],
            "retrieved_chunks": [item.model_dump(mode="json") for item in all_chunks.values()],
            "visual_evidence": [item.model_dump(mode="json") for item in visual_evidence],
            "evidence_status": (
                "sufficient"
                if evidence_statuses and all(item == "sufficient" for item in evidence_statuses)
                else "insufficient_evidence"
            ),
            "max_risk": self._max_risk(all_risks),
            "failures": failures,
            "reused_inspection_count": reused_count,
            "new_inference_count": len(inspections) - reused_count,
            "tool_chain": tool_chain,
            "performance": [{"operation": "mvp_inspection", "duration_ms": elapsed_ms}],
        }
        status = "completed" if inspections else "failed"
        stored = self.memory.update_task(task.id, status=status, result=result)
        response = (
            f"完成 {len(inspections)} 张图片巡检，最高风险为 {result['max_risk']}；"
            f"复用 {reused_count} 个已有检测结果。"
        )
        self.memory.add_message(session_id, "assistant", response, {"task_id": task.id})
        return {
            "session_id": session_id,
            "task_id": stored.id,
            "status": status,
            "final_response": response,
            **result,
        }

    def _previous(self, session_id: str) -> StoredTask:
        previous = self.memory.previous_completed(session_id)
        if previous is None:
            raise ValueError("No completed inspection task is available in this session")
        return previous

    def _high_risk(self, request: MvpChatInput, session_id: str) -> dict[str, Any]:
        previous = self._previous(session_id)
        task = self.memory.create_task(
            session_id,
            "高风险结果展开",
            request.message,
            task_id=request.task_id,
        )
        risks = [
            item
            for item in previous.result.get("risks", [])
            if RISK_ORDER.get(str(item.get("severity")), 0) >= RISK_ORDER["high"]
        ]
        result = {
            "action": "high_risk",
            "source_task_id": previous.id,
            "risks": risks,
            "inspections": previous.result.get("inspections", []),
            "retrieved_chunks": previous.result.get("retrieved_chunks", []),
            "max_risk": previous.result.get("max_risk", "low"),
            "new_inference_count": 0,
            "reused_inspection_count": len(previous.result.get("inspections", [])),
            "tool_chain": ["query_previous_task"],
            "performance": [],
        }
        self.memory.update_task(task.id, status="completed", result=result)
        response = f"已从任务 {previous.id} 复用结果，筛出 {len(risks)} 条高风险记录。"
        self.memory.add_message(session_id, "assistant", response, {"task_id": task.id})
        return {
            "session_id": session_id,
            "task_id": task.id,
            "status": "completed",
            "final_response": response,
            **result,
        }

    @staticmethod
    def _report_input(previous: StoredTask, task_id: str) -> ReportInput:
        inspections = [
            InspectionResult.model_validate(item) for item in previous.result.get("inspections", [])
        ]
        risks = [RiskAssessment.model_validate(item) for item in previous.result.get("risks", [])]
        chunks = [
            DocumentChunk.model_validate(item)
            for item in previous.result.get("retrieved_chunks", [])
        ]
        citations = [
            CitationStatement(
                chunk_id=chunk.chunk_id,
                standard_name=chunk.document_name,
                source_path=chunk.source_path,
                article=chunk.article,
                page=chunk.page,
                quoted_content=chunk.content[:300],
            )
            for chunk in chunks
        ]
        findings = [
            f"{detection.label}，置信度 {detection.confidence:.3f}，来源 {inspection.source_path}"
            for inspection in inspections
            for detection in inspection.detections
        ]
        recommendations = sorted({action for risk in risks for action in risk.recommended_actions})
        visual_evidence: list[ReportEvidence] = []
        for item in previous.result.get("visual_evidence", []):
            if not isinstance(item, dict):
                continue
            if "source_path" in item:
                visual_evidence.append(ReportEvidence.model_validate(item))
                continue
            # Agent-native EvidenceRecord uses image_path/bbox and keeps the
            # canonical label in metadata.  Convert it without weakening either
            # schema at the persistence boundary.
            metadata = item.get("metadata", {})
            visual_evidence.append(
                ReportEvidence(
                    source_path=Path(str(item["image_path"])),
                    visualization_path=Path(str(item["visualization_path"])),
                    label=str(
                        metadata.get("label", "unknown")
                        if isinstance(metadata, dict)
                        else "unknown"
                    ),
                    confidence=float(item["confidence"]),
                    bounding_box=item["bbox"],
                    source_model=str(item["source_model"]),
                )
            )
        return ReportInput(
            task_id=task_id,
            session_id=previous.session_id,
            title="BuildGuard 施工巡检报告",
            sources=[str(item.source_path) for item in inspections],
            findings=findings,
            risks=risks,
            retrieved_chunks=chunks,
            citation_statements=citations,
            recommendations=recommendations,
            visual_evidence=visual_evidence,
            tool_chain=[
                *previous.result.get("tool_chain", []),
                "build_report",
            ],
            performance=previous.result.get("performance", []),
        )

    def _request_report(self, request: MvpChatInput, session_id: str) -> dict[str, Any]:
        previous = self._previous(session_id)
        task = self.memory.create_task(
            session_id,
            "生成巡检报告",
            request.message,
            task_id=request.task_id,
            status="WAIT_FOR_CONFIRMATION",
        )
        report_input = self._report_input(previous, task.id)
        report_started = time.perf_counter()
        draft = self.reports.build(report_input)
        self.memory.record_performance(
            "report_generation",
            (time.perf_counter() - report_started) * 1000,
            metrics={"task_id": task.id, "report_type": "inspection"},
        )
        result = {
            "action": "report",
            "source_task_id": previous.id,
            "report_draft": draft.model_dump(mode="json"),
            "new_inference_count": 0,
            "reused_inspection_count": len(previous.result.get("inspections", [])),
            "pending_confirmation": {
                "tool_name": "write_report",
                "parameter_summary": {
                    "title": report_input.title,
                    "format": ["markdown", "html"],
                },
                "access_paths": [str(self.reports.output_dir)],
                "risk": "This action writes report files to the local workspace.",
            },
        }
        self.memory.update_task(
            task.id,
            status="WAIT_FOR_CONFIRMATION",
            result=result,
        )
        response = "报告草稿已完成并通过引用检查；写入 Markdown/HTML 前需要用户确认。"
        self.memory.add_message(session_id, "assistant", response, {"task_id": task.id})
        return {
            "session_id": session_id,
            "task_id": task.id,
            "status": "WAIT_FOR_CONFIRMATION",
            "final_response": response,
            **result,
        }

    def _request_event_report(
        self,
        request: MvpChatInput,
        session_id: str,
    ) -> dict[str, Any]:
        events = self.event_provider() if self.event_provider is not None else []
        if not events:
            raise ValueError("No realtime risk events are available for reporting")
        task = self.memory.create_task(
            session_id,
            "生成风险事件报告",
            request.message,
            task_id=request.task_id,
            status="WAIT_FOR_CONFIRMATION",
        )
        event_types = sorted({event.event_type for event in events})
        rag_request = RagSearchInput(
            query="施工安全规范 " + " ".join(event_types),
            top_k=5,
        )
        search = (
            self.advanced_rag.retrieve(rag_request)
            if self.advanced_rag is not None
            else self.rag.search(rag_request)
        )
        citations = [
            CitationStatement(
                chunk_id=chunk.chunk_id,
                standard_name=chunk.document_name,
                source_path=chunk.source_path,
                article=chunk.article,
                page=chunk.page,
                quoted_content=chunk.content[:300],
            )
            for chunk in search.chunks
        ]
        retrieved_evidence = self._retrieved_evidence(
            search.chunks,
            search.scores,
        )
        risks: list[RiskAssessment] = []
        for event in events:
            duration_seconds = max(
                0.0,
                (event.last_seen_at - event.started_at).total_seconds(),
            )
            synthetic_inspection = InspectionResult(
                source_path=Path("realtime") / f"{event.camera_id}.frame",
                detections=[
                    Detection(
                        label=event.event_type,
                        confidence=event.max_confidence,
                        bounding_box=event.region,
                        source_model="realtime-event-engine",
                        attributes={
                            "duration_seconds": duration_seconds,
                            "repeat_count": sum(
                                1
                                for candidate in events
                                if candidate.camera_id == event.camera_id
                                and candidate.event_type == event.event_type
                            ),
                        },
                    )
                ],
                model_name="realtime-event-engine",
                processing_ms=0,
                success=True,
            )
            assessed = self.risk.assess(
                synthetic_inspection,
                retrieved_evidence,
            ).assessment
            risks.append(
                assessed.model_copy(
                    update={
                        "summary": (
                            f"实时事件 {event.event_type}，状态 {event.status.value}，"
                            f"持续 {duration_seconds:.1f} 秒，"
                            f"最大置信度 {event.max_confidence:.3f}；"
                            f"{assessed.summary}"
                        ),
                        "recommended_actions": [
                            *assessed.recommended_actions,
                            "人工复核事件证据并按现场制度处置",
                        ],
                    }
                )
            )
        report_input = ReportInput(
            task_id=task.id,
            session_id=session_id,
            title="BuildGuard 实时风险事件报告",
            report_type="realtime_event",
            sources=sorted({event.camera_id for event in events}),
            findings=[
                (
                    f"{event.camera_id}: {event.event_type} / {event.status.value}; "
                    f"event_id={event.id}"
                )
                for event in events
            ],
            risks=risks,
            retrieved_chunks=search.chunks,
            citation_statements=citations,
            recommendations=["由现场负责人复核关键帧并记录闭环处置结果"],
            visual_evidence=[
                ReportEvidence(
                    source_path=(
                        event.max_confidence_frame_path
                        or event.start_frame_path
                        or event.end_frame_path
                        or Path("realtime") / f"{event.camera_id}.frame"
                    ),
                    visualization_path=(event.max_confidence_frame_path or event.start_frame_path),
                    label=event.event_type,
                    confidence=event.max_confidence,
                    bounding_box=event.region,
                    source_model="realtime-event-engine",
                    clip_path=event.clip_path,
                )
                for event in events
            ],
            tool_chain=[
                "query_recent_events",
                "search_construction_standards",
                "build_report",
            ],
        )
        report_started = time.perf_counter()
        draft = self.reports.build(report_input)
        self.memory.record_performance(
            "report_generation",
            (time.perf_counter() - report_started) * 1000,
            metrics={"task_id": task.id, "report_type": "realtime_event"},
        )
        result = {
            "action": "event_report",
            "event_ids": [event.id for event in events],
            "report_draft": draft.model_dump(mode="json"),
            "new_inference_count": 0,
            "pending_confirmation": {
                "tool_name": "write_report",
                "parameter_summary": {
                    "title": report_input.title,
                    "event_count": len(events),
                },
                "access_paths": [str(self.reports.output_dir)],
                "risk": "This action writes an event report to the local workspace.",
            },
        }
        self.memory.update_task(
            task.id,
            status="WAIT_FOR_CONFIRMATION",
            result=result,
        )
        return {
            "session_id": session_id,
            "task_id": task.id,
            "status": "WAIT_FOR_CONFIRMATION",
            "final_response": (f"已基于 {len(events)} 个实时事件生成草稿；写入前需要用户确认。"),
            **result,
        }

    def process_realtime_event(self, event: RealtimeRiskEvent) -> dict[str, Any]:
        """Run the deliberate, auditable event loop outside camera inference workers."""
        session_id = f"realtime-{event.camera_id}"
        self.memory.ensure_session(session_id, f"Realtime camera {event.camera_id}")
        task_id = str(uuid5(NAMESPACE_URL, f"buildguard:realtime-event:{event.id}"))
        existing = self.memory.get_task(task_id)
        if existing is not None and existing.status == "completed":
            return existing.result
        task = existing or self.memory.create_task(
            session_id,
            f"Realtime risk analysis: {event.event_type}",
            f"Analyze confirmed event {event.id}",
            task_id=task_id,
        )
        request = RagSearchInput(
            query=f"施工安全规范 {event.event_type}",
            top_k=5,
        )
        search = (
            self.advanced_rag.retrieve(request)
            if self.advanced_rag is not None
            else self.rag.search(request)
        )
        evidence = self._retrieved_evidence(search.chunks, search.scores)
        history = self.event_provider() if self.event_provider is not None else [event]
        recurrence = sum(
            1
            for candidate in history
            if candidate.camera_id == event.camera_id and candidate.event_type == event.event_type
        )
        duration_seconds = max(
            0.0,
            (event.last_seen_at - event.started_at).total_seconds(),
        )
        inspection = InspectionResult(
            source_path=Path("realtime") / f"{event.camera_id}.frame",
            detections=[
                Detection(
                    label=event.event_type,
                    confidence=event.max_confidence,
                    bounding_box=event.region,
                    source_model="realtime-event-engine",
                    attributes={
                        "duration_seconds": duration_seconds,
                        "repeat_count": max(1, recurrence),
                    },
                )
            ],
            model_name="realtime-event-engine",
            processing_ms=0,
            success=True,
        )
        risk = self.risk.assess(inspection, evidence).assessment
        citations = [
            CitationStatement(
                chunk_id=chunk.chunk_id,
                standard_name=chunk.document_name,
                source_path=chunk.source_path,
                article=chunk.article,
                page=chunk.page,
                quoted_content=chunk.content[:300],
            )
            for chunk in search.chunks
        ]
        key_frame = (
            event.max_confidence_frame_path
            or event.start_frame_path
            or event.end_frame_path
            or inspection.source_path
        )
        _label_zh: dict[str, str] = {
            "structural_damage": "结构损伤",
            "structural_crack": "结构裂缝",
            "structural_corrosion": "钢筋锈蚀",
            "helmet_missing": "未佩戴安全帽",
            "safety_vest_missing": "未穿反光背心",
            "dangerous_zone": "危险区域闯入",
            "static_defect": "静态缺陷",
            "emergency": "紧急情况",
        }
        label_zh = _label_zh.get(event.event_type, event.event_type)
        duration_desc = (
            f"持续 {duration_seconds:.0f} 秒" if duration_seconds >= 1 else "瞬时检出"
        )
        recurrence_desc = f"本摄像头本类型累计 {recurrence} 次" if recurrence > 1 else "首次检出"
        finding_text = (
            f"【{label_zh}】置信度 {event.max_confidence:.0%}，{duration_desc}，{recurrence_desc}"
        )
        report_input = ReportInput(
            task_id=task.id,
            session_id=session_id,
            title=f"实时安全事件报告 — {label_zh}",
            report_type="realtime_event_draft",
            sources=[event.camera_id],
            findings=[finding_text],
            risks=[risk],
            retrieved_chunks=search.chunks,
            citation_statements=citations,
            recommendations=[*risk.recommended_actions, "现场负责人复核并记录处置闭环"],
            visual_evidence=[
                ReportEvidence(
                    source_path=key_frame,
                    visualization_path=(event.max_confidence_frame_path or event.start_frame_path),
                    label=label_zh,
                    confidence=event.max_confidence,
                    bounding_box=event.region,
                    source_model="realtime-event-engine",
                    clip_path=event.clip_path,
                )
            ],
            tool_chain=[
                "query_recent_events",
                "search_construction_standards",
                "assess_risk",
                "build_report_draft",
            ],
        )
        report_started = time.perf_counter()
        draft = self.reports.build(report_input)
        self.memory.record_performance(
            "report_generation",
            (time.perf_counter() - report_started) * 1000,
            metrics={"task_id": task.id, "report_type": "realtime_event_draft"},
        )
        evidence_paths = [
            str(path)
            for path in (
                event.start_frame_path,
                event.max_confidence_frame_path,
                event.end_frame_path,
                event.clip_path,
            )
            if path is not None
        ]
        risk_event_id = self.memory.save_risk_event(
            session_id,
            event_type=event.event_type,
            severity=risk.severity.value,
            description=risk.summary,
            evidence_paths=evidence_paths,
        )
        result = {
            "action": "realtime_slow_loop",
            "event_id": event.id,
            "risk_event_id": risk_event_id,
            "risk": risk.model_dump(mode="json"),
            "retrieved_chunks": [item.model_dump(mode="json") for item in search.chunks],
            "report_draft": draft.model_dump(mode="json"),
            "notification": {
                "severity": risk.severity.value,
                "message": risk.summary,
                "requires_acknowledgement": True,
            },
            "tool_chain": report_input.tool_chain,
        }
        self.memory.update_task(task.id, status="completed", result=result)
        self.memory.add_message(
            session_id,
            "assistant",
            f"Realtime event {event.id} assessed as {risk.severity.value}.",
            {"task_id": task.id, "event_id": event.id},
        )
        return result

    def _history(self, request: MvpChatInput, session_id: str) -> dict[str, Any]:
        tasks = self.memory.list_tasks(session_id=session_id, limit=20)
        task = self.memory.create_task(
            session_id,
            "历史任务查询",
            request.message,
            task_id=request.task_id,
            status="completed",
            result={"action": "history", "task_count": len(tasks)},
        )
        response = f"当前会话已有 {len(tasks)} 个历史任务。"
        return {
            "session_id": session_id,
            "task_id": task.id,
            "status": "completed",
            "final_response": response,
            "tasks": [item.model_dump(mode="json") for item in tasks],
            "new_inference_count": 0,
        }

    def chat(self, request: MvpChatInput) -> dict[str, Any]:
        session_id = request.session_id or str(uuid4())
        self.memory.ensure_session(
            session_id,
            self.memory.title_from_message(request.message, session_id),
        )
        self.memory.add_message(session_id, "user", request.message)
        action = self._infer_action(request)
        if action == "inspect":
            return self._inspect(request, session_id)
        if action == "high_risk":
            return self._high_risk(request, session_id)
        if action == "report":
            return self._request_report(request, session_id)
        if action == "event_report":
            return self._request_event_report(request, session_id)
        return self._history(request, session_id)

    def confirm(self, task_id: str, approved: bool) -> dict[str, Any]:
        task = self.memory.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task.status != "WAIT_FOR_CONFIRMATION":
            raise ValueError("Task is not waiting for confirmation")
        if not approved:
            result = {**task.result, "confirmation": "denied"}
            self.memory.update_task(task_id, status="failed", result=result)
            return {
                "session_id": task.session_id,
                "task_id": task.id,
                "status": "safe_failure",
                "final_response": "用户拒绝写入报告；未创建报告文件。",
            }
        draft = ReportDraft.model_validate(task.result["report_draft"])
        export_started = time.perf_counter()
        artifact = self.reports.export(draft, confirmed=True)
        self.memory.record_performance(
            "report_export",
            (time.perf_counter() - export_started) * 1000,
            metrics={"task_id": task.id},
        )
        report_id = self.memory.save_report(draft, artifact)
        result = {
            **task.result,
            "confirmation": "approved",
            "report_id": report_id,
            "report_path": str(artifact.markdown_path),
            "html_path": str(artifact.html_path),
            "pdf": artifact.pdf.model_dump(mode="json"),
        }
        self.memory.update_task(task_id, status="completed", result=result)
        response = f"报告已生成：{artifact.markdown_path}"
        self.memory.add_message(
            task.session_id,
            "assistant",
            response,
            {"task_id": task.id, "report_id": report_id},
        )
        return {
            "session_id": task.session_id,
            "task_id": task.id,
            "status": "completed",
            "final_response": response,
            **result,
        }

    def export_latest_report(
        self,
        session_id: str,
        *,
        filename: str | None = None,
        confirmed: bool,
    ) -> dict[str, Any]:
        """Export the latest completed inspection after an external permission check."""
        if not confirmed:
            raise PermissionError("Report export requires explicit user confirmation")
        previous = self._previous(session_id)
        task = self.memory.create_task(
            session_id,
            "生成巡检报告",
            "Agent requested a report from the latest completed inspection.",
            status="running",
        )
        report_input = self._report_input(previous, task.id)
        report_started = time.perf_counter()
        draft = self.reports.build(report_input)
        self.memory.record_performance(
            "report_generation",
            (time.perf_counter() - report_started) * 1000,
            metrics={"task_id": task.id, "report_type": "inspection"},
        )
        export_started = time.perf_counter()
        artifact = self.reports.export(
            draft,
            confirmed=True,
            filename=filename,
        )
        self.memory.record_performance(
            "report_export",
            (time.perf_counter() - export_started) * 1000,
            metrics={"task_id": task.id},
        )
        report_id = self.memory.save_report(draft, artifact)
        result = {
            "action": "report",
            "source_task_id": previous.id,
            "report_id": report_id,
            "report_path": str(artifact.markdown_path),
            "html_path": str(artifact.html_path),
            "pdf_path": (
                str(artifact.pdf.path)
                if artifact.pdf.available and artifact.pdf.path is not None
                else None
            ),
            "verified_citation_count": artifact.verified_citation_count,
        }
        self.memory.update_task(task.id, status="completed", result=result)
        return {"task_id": task.id, **result}
