"""End-to-end evidence reconstruction with resumable run records."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.agents.intake import assess_intake
from app.evidence.conflicts import detect_conflicts
from app.evidence.document_parser import parse_pdf
from app.evidence.fact_extractor import (
    EvidenceExtractor,
    ExtractionResult,
    LocalEvidenceExtractor,
)
from app.evidence.image_parser import parse_image
from app.evidence.timeline import merge_timeline
from app.evidence.video_parser import parse_video
from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import (
    EvidenceNode,
    Fact,
    ProcessingStatus,
    SourceKind,
    TimelineEvent,
)


@dataclass(frozen=True)
class ReconstructionSummary:
    case_id: str
    run_id: str
    status: str
    processed_sources: tuple[str, ...]
    failed_sources: dict[str, str]
    node_count: int
    fact_count: int
    timeline_event_count: int
    conflict_count: int
    missing_materials: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "status": self.status,
            "processed_sources": list(self.processed_sources),
            "failed_sources": self.failed_sources,
            "node_count": self.node_count,
            "fact_count": self.fact_count,
            "timeline_event_count": self.timeline_event_count,
            "conflict_count": self.conflict_count,
            "missing_materials": list(self.missing_materials),
        }


class EvidenceReconstructionPipeline:
    def __init__(
        self,
        workspace: CaseWorkspace,
        extractor: EvidenceExtractor | None = None,
    ):
        self.workspace = workspace
        self.extractor = extractor or LocalEvidenceExtractor()

    def reconstruct(self, case_id: str) -> ReconstructionSummary:
        store = self.workspace.store(case_id)
        sources = store.list_sources(case_id)
        if not sources:
            raise ValueError(f"Case {case_id} has no source files.")
        run_id = f"RUN-{uuid.uuid4().hex[:16].upper()}"
        store.start_run(run_id, case_id, "evidence_reconstruction")
        case_dir = self.workspace.case_dir(case_id)
        derived_dir = case_dir / "derived"
        response_dir = derived_dir / "model_responses" / run_id
        response_dir.mkdir(parents=True, exist_ok=True)

        processed: list[str] = []
        failures: dict[str, str] = {}
        facts: list[Fact] = []
        events: list[TimelineEvent] = []
        for source in sources:
            store.update_source_status(source.source_id, ProcessingStatus.PROCESSING)
            try:
                store.clear_source_derivatives(source.source_id)
                path = self.workspace.resolve_source(source)
                source_nodes, source_facts, source_events = self._process_source(
                    source,
                    path,
                    derived_dir,
                    response_dir,
                    store,
                )
                for fact in source_facts:
                    store.add_fact(fact)
                facts.extend(source_facts)
                events.extend(source_events)
                store.update_source_status(source.source_id, ProcessingStatus.PARSED)
                processed.append(source.source_id)
            except Exception as exc:  # every source failure is persisted
                reason = f"{type(exc).__name__}: {exc}"
                failures[source.source_id] = reason
                store.update_source_status(
                    source.source_id, ProcessingStatus.FAILED, reason
                )
                store.audit(
                    case_id,
                    "source_processing_failed",
                    {
                        "run_id": run_id,
                        "source_id": source.source_id,
                        "failure_reason": reason,
                        "next_step": _next_step_for(exc),
                    },
                    "evidence_pipeline",
                )

        timeline = merge_timeline(events)
        conflicts = detect_conflicts(facts)
        store.replace_timeline(case_id, timeline)
        store.replace_conflicts(case_id, conflicts)
        intake = assess_intake(sources)
        status = "passed" if not failures else ("partial" if processed else "failed")
        next_step = (
            ""
            if not failures
            else "Review failed source records, install missing parser dependencies, "
            "or validate the local vLLM response before rerunning."
        )
        summary = ReconstructionSummary(
            case_id=case_id,
            run_id=run_id,
            status=status,
            processed_sources=tuple(processed),
            failed_sources=failures,
            node_count=len(store.list_nodes(case_id)),
            fact_count=len(store.list_facts(case_id)),
            timeline_event_count=len(timeline),
            conflict_count=len(conflicts),
            missing_materials=intake.missing_materials,
        )
        store.finish_run(
            run_id,
            status,
            failure_reason=json.dumps(failures, ensure_ascii=False),
            next_step=next_step,
            details=summary.to_dict(),
        )
        store.audit(
            case_id,
            "evidence_reconstruction_finished",
            summary.to_dict(),
            "evidence_pipeline",
        )
        return summary

    def _process_source(
        self,
        source: Any,
        path: Path,
        derived_dir: Path,
        response_dir: Path,
        store: Any,
    ) -> tuple[list[EvidenceNode], list[Fact], list[TimelineEvent]]:
        if source.kind is SourceKind.IMAGE:
            node = parse_image(source, path)
            store.add_node(node)
            result = self.extractor.extract_images(source.case_id, [(node, path)])
            self._record_response(response_dir, source.source_id, 1, result)
            return [node], list(result.facts), list(result.timeline_events)

        if source.kind is SourceKind.PDF:
            document = parse_pdf(source, path, derived_dir)
            for node in document.nodes:
                store.add_node(node)
            facts: list[Fact] = []
            events: list[TimelineEvent] = []
            response_index = 0
            for node in document.nodes:
                if node.content:
                    response_index += 1
                    result = self.extractor.extract_text(source.case_id, node)
                    self._record_response(
                        response_dir, source.source_id, response_index, result
                    )
                    facts.extend(result.facts)
                    events.extend(result.timeline_events)

            scanned_pairs: list[tuple[EvidenceNode, Path]] = []
            page_path_by_number = {
                _page_number(path): path for path in document.page_images
            }
            for node in document.nodes:
                if node.metadata.get("is_scanned"):
                    page_path = page_path_by_number.get(int(node.locator["page"]))
                    if page_path:
                        scanned_pairs.append((node, page_path))
            for batch in _batches(scanned_pairs, 8):
                response_index += 1
                result = self.extractor.extract_images(source.case_id, batch)
                self._record_response(
                    response_dir, source.source_id, response_index, result
                )
                facts.extend(result.facts)
                events.extend(result.timeline_events)
            return list(document.nodes), facts, events

        if source.kind is SourceKind.VIDEO:
            video = parse_video(source, path, derived_dir)
            for node in video.nodes:
                store.add_node(node)
            video_facts: list[Fact] = []
            video_events: list[TimelineEvent] = []
            pairs = list(zip(video.nodes, video.frame_paths, strict=True))
            timestamp_by_node = {
                node.node_id: float(node.locator["timestamp_seconds"])
                for node in video.nodes
            }
            for position, node in enumerate(video.nodes, start=1):
                timestamp = timestamp_by_node[node.node_id]
                video_events.append(
                    TimelineEvent(
                        event_id=f"EVENT-{node.node_id[5:]}",
                        case_id=source.case_id,
                        label=f"视频关键帧 t={timestamp:.3f}秒",
                        relative_order=position,
                        source_node_ids=(node.node_id,),
                        timestamp_seconds=timestamp,
                        confidence=1.0,
                    )
                )
            for response_index, batch in enumerate(_batches(pairs, 8), start=1):
                result = self.extractor.extract_images(source.case_id, batch)
                self._record_response(
                    response_dir, source.source_id, response_index, result
                )
                video_facts.extend(result.facts)
                for event in result.timeline_events:
                    timestamps = [
                        timestamp_by_node[node_id]
                        for node_id in event.source_node_ids
                        if node_id in timestamp_by_node
                    ]
                    video_events.append(
                        TimelineEvent(
                            event_id=event.event_id,
                            case_id=event.case_id,
                            label=event.label,
                            relative_order=event.relative_order,
                            source_node_ids=event.source_node_ids,
                            timestamp_seconds=min(timestamps) if timestamps else None,
                            confidence=event.confidence,
                            created_at=event.created_at,
                        )
                    )
            return list(video.nodes), video_facts, video_events

        raise ValueError(f"Unsupported source kind: {source.kind}")

    @staticmethod
    def _record_response(
        directory: Path,
        source_id: str,
        index: int,
        result: ExtractionResult,
    ) -> None:
        payload = {
            "source_id": source_id,
            "model": result.model,
            "latency_seconds": result.latency_seconds,
            "usage": result.usage,
            "facts": [fact.to_dict() for fact in result.facts],
            "timeline_events": [
                event.to_dict() for event in result.timeline_events
            ],
            "raw_response": result.raw_response,
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        destination = directory / f"{source_id}-{index:03d}-{digest[:12]}.json"
        destination.write_bytes(encoded + b"\n")


def _batches(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _page_number(path: Path) -> int:
    return int(path.stem.rsplit("_", 1)[-1])


def _next_step_for(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "DependencyUnavailable":
        return "Install the evidence parser dependencies, then rerun this case."
    if name == "ModelResponseError":
        return (
            "Inspect the saved local vLLM response and retry once with the strict "
            "evidence schema."
        )
    return "Inspect the source signature/decoder error and verify the original file."
