"""Case intake service over the existing workspace and Evidence Graph."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.agents.intake import assess_intake
from app.evidence.fact_extractor import ExtractionResult
from app.evidence.pipeline import EvidenceReconstructionPipeline
from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import EvidenceNode, SourceRole
from app.schemas.ui import (
    CaseMetadata,
    CaseSummary,
    PartyRole,
    UploadedSource,
    WorkflowMode,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
METADATA_EVENT = "case_metadata_saved"
THREAD_EVENT = "workflow_thread_registered"
RECONSTRUCTION_EVENT = "ui_reconstruction_completed"
COLLABORATION_EVENT = "collaboration_material_added"
OWNER_TASK_EVENT = "owner_task_status_updated"
OWNER_COMMUNICATION_EVENT = "owner_communication_recorded"


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


class EmptyMockEvidenceExtractor:
    """No-inference extractor for uploaded files in mock mode.

    Parsers still create real document/image/video nodes. No facts are invented;
    users must load a declared synthetic fixture or run local-vLLM for fact
    extraction.
    """

    name = "mock-no-inference"

    @staticmethod
    def _empty() -> ExtractionResult:
        return ExtractionResult(
            facts=(),
            timeline_events=(),
            model=EmptyMockEvidenceExtractor.name,
            latency_seconds=0.0,
            usage={},
            raw_response='{"observations":[],"timeline":[]}',
        )

    def extract_images(
        self,
        case_id: str,
        nodes_and_paths: list[tuple[EvidenceNode, Path]],
    ) -> ExtractionResult:
        del case_id, nodes_and_paths
        return self._empty()

    def extract_text(
        self, case_id: str, node: EvidenceNode
    ) -> ExtractionResult:
        del case_id, node
        return self._empty()


class CaseService:
    def __init__(self, case_root: Path | str = Path("data/cases")):
        self.workspace = CaseWorkspace(case_root)

    def create_case(
        self,
        *,
        case_id: str | None = None,
        accident_time: datetime | None = None,
        location: str = "",
        jurisdiction: str = "CN",
        party_role: PartyRole | str = PartyRole.INSURED_DRIVER,
        manual_delivery_date: date | None = None,
        files: Iterable[Path | str] = (),
        default_role: SourceRole | str = SourceRole.OTHER,
    ) -> CaseSummary:
        selected = self.workspace.create_case(case_id)
        now = now_shanghai()
        metadata = CaseMetadata(
            case_id=selected,
            accident_time=accident_time,
            location=location,
            jurisdiction=jurisdiction or "CN",
            party_role=PartyRole(party_role),
            manual_delivery_date=manual_delivery_date,
            created_at=now,
            updated_at=now,
        )
        store = self.workspace.store(selected)
        store.audit(
            selected,
            METADATA_EVENT,
            metadata.model_dump(mode="json"),
            "case_intake_ui",
        )
        role = SourceRole(default_role)
        for file_path in files:
            path = Path(file_path)
            self.workspace.ingest_file(
                selected,
                path,
                role=role,
                original_name=path.name,
            )
        return self.summary(selected)

    def update_metadata(
        self,
        case_id: str,
        *,
        accident_time: datetime | None = None,
        location: str | None = None,
        jurisdiction: str | None = None,
        party_role: PartyRole | str | None = None,
        manual_delivery_date: date | None = None,
    ) -> CaseMetadata:
        current = self.metadata(case_id)
        updated = current.model_copy(
            update={
                "accident_time": (
                    accident_time
                    if accident_time is not None
                    else current.accident_time
                ),
                "location": location if location is not None else current.location,
                "jurisdiction": (
                    jurisdiction
                    if jurisdiction is not None
                    else current.jurisdiction
                ),
                "party_role": (
                    PartyRole(party_role)
                    if party_role is not None
                    else current.party_role
                ),
                "manual_delivery_date": (
                    manual_delivery_date
                    if manual_delivery_date is not None
                    else current.manual_delivery_date
                ),
                "updated_at": now_shanghai(),
            }
        )
        self.workspace.store(case_id).audit(
            case_id,
            METADATA_EVENT,
            updated.model_dump(mode="json"),
            "case_intake_ui",
        )
        return updated

    def ingest_files(
        self,
        case_id: str,
        files: Iterable[Path | str],
        *,
        role: SourceRole | str = SourceRole.OTHER,
    ) -> list[UploadedSource]:
        selected_role = SourceRole(role)
        for file_path in files:
            path = Path(file_path)
            self.workspace.ingest_file(
                case_id,
                path,
                role=selected_role,
                original_name=path.name,
            )
        return self.sources(case_id)

    def record_collaboration_materials(
        self,
        case_id: str,
        source_ids: Iterable[str],
        *,
        provider: str,
    ) -> str:
        """Record who supplied materials without changing the evidence itself."""
        return self.workspace.store(case_id).audit(
            case_id,
            COLLABORATION_EVENT,
            {
                "source_ids": list(source_ids),
                "provider": provider,
                "status": "recorded",
            },
            "vehicle_owner_ui",
        )

    def record_owner_task_status(
        self,
        case_id: str,
        task_id: str,
        *,
        status: str,
    ) -> str:
        if status not in {"completed", "in_progress", "dismissed"}:
            raise ValueError("不支持的任务状态。")
        return self.workspace.store(case_id).audit(
            case_id,
            OWNER_TASK_EVENT,
            {
                "task_id": task_id,
                "status": status,
            },
            "vehicle_owner",
        )

    def record_owner_communication(
        self,
        case_id: str,
        *,
        target: str,
        result: str,
    ) -> str:
        """Store a short outcome, never an automated external submission."""
        return self.workspace.store(case_id).audit(
            case_id,
            OWNER_COMMUNICATION_EVENT,
            {
                "target": target,
                "result": result.strip(),
                "status": "recorded",
                "external_submission": False,
            },
            "vehicle_owner",
        )

    def update_source_role(
        self, case_id: str, source_id: str, role: SourceRole | str
    ) -> UploadedSource:
        store = self.workspace.store(case_id)
        source = store.get_source(source_id)
        if source.case_id != case_id:
            raise KeyError(source_id)
        store.update_source_role(source_id, SourceRole(role))
        return next(item for item in self.sources(case_id) if item.source_id == source_id)

    def metadata(self, case_id: str) -> CaseMetadata:
        store = self.workspace.store(case_id)
        events = store.list_audit_events(case_id)
        payload = next(
            (
                item["payload"]
                for item in reversed(events)
                if item["event_type"] == METADATA_EVENT
            ),
            None,
        )
        if payload:
            return CaseMetadata.model_validate(payload)
        case = store.export_case(case_id)["case"]
        created = datetime.fromisoformat(case["created_at"]).astimezone(SHANGHAI)
        return CaseMetadata(
            case_id=case_id,
            created_at=created,
            updated_at=datetime.fromisoformat(case["updated_at"]).astimezone(
                SHANGHAI
            ),
        )

    def sources(self, case_id: str) -> list[UploadedSource]:
        store = self.workspace.store(case_id)
        failures = {
            event["payload"].get("source_id"): event["payload"].get(
                "failure_reason", "解析失败"
            )
            for event in store.list_audit_events(case_id)
            if event["event_type"] == "source_processing_failed"
        }
        result: list[UploadedSource] = []
        for source in store.list_sources(case_id):
            issues: list[str] = []
            if source.source_id in failures:
                issues.append(str(failures[source.source_id]))
            if source.size_bytes == 0:
                issues.append("空文件")
            result.append(
                UploadedSource(
                    source_id=source.source_id,
                    original_name=source.original_name,
                    kind=source.kind.value,
                    role=source.role.value,
                    media_type=source.media_type,
                    size_bytes=source.size_bytes,
                    sha256=source.sha256,
                    processing_status=source.status.value,
                    quality_issues=issues,
                )
            )
        return result

    def export_case(self, case_id: str) -> dict[str, Any]:
        store = self.workspace.store(case_id)
        payload = store.export_case(case_id)
        payload["metadata"] = self.metadata(case_id).model_dump(mode="json")
        payload["intake"] = assess_intake(
            store.list_sources(case_id)
        ).to_dict()
        return payload

    def case_ids(self) -> list[str]:
        if not self.workspace.root.exists():
            return []
        return sorted(
            path.name
            for path in self.workspace.root.iterdir()
            if path.is_dir() and (path / "case.sqlite3").is_file()
        )

    def summary(self, case_id: str) -> CaseSummary:
        exported = self.export_case(case_id)
        latest_thread = self.latest_thread(case_id)
        return CaseSummary(
            metadata=self.metadata(case_id),
            source_count=len(exported["sources"]),
            fact_count=len(exported["facts"]),
            conflict_count=len(exported["conflicts"]),
            latest_thread_id=(
                latest_thread.get("thread_id") if latest_thread else None
            ),
            latest_workflow_status=(
                latest_thread.get("status") if latest_thread else None
            ),
        )

    def list_cases(self) -> list[CaseSummary]:
        result: list[CaseSummary] = []
        for case_id in self.case_ids():
            try:
                result.append(self.summary(case_id))
            except (KeyError, ValueError, OSError, sqlite3.Error):
                continue
        return sorted(
            result, key=lambda item: item.metadata.updated_at, reverse=True
        )

    def register_thread(
        self,
        case_id: str,
        thread_id: str,
        *,
        mode: WorkflowMode | str,
        status: str,
        current_node: str = "pending",
        recoverable: bool = False,
    ) -> str:
        return self.workspace.store(case_id).audit(
            case_id,
            THREAD_EVENT,
            {
                "thread_id": thread_id,
                "mode": WorkflowMode(mode).value,
                "status": status,
                "current_node": current_node,
                "recoverable": recoverable,
            },
            "workflow_service",
        )

    def latest_thread(self, case_id: str) -> dict[str, Any] | None:
        events = self.workspace.store(case_id).list_audit_events(case_id)
        return next(
            (
                event["payload"]
                for event in reversed(events)
                if event["event_type"] == THREAD_EVENT
            ),
            None,
        )

    def reconstruct(
        self, case_id: str, *, mode: WorkflowMode | str
    ) -> dict[str, Any]:
        selected_mode = WorkflowMode(mode)
        store = self.workspace.store(case_id)
        inputs_hash = self.source_inputs_hash(case_id)
        previous = next(
            (
                event["payload"]
                for event in reversed(store.list_audit_events(case_id))
                if event["event_type"] == RECONSTRUCTION_EVENT
                and event["payload"].get("inputs_hash") == inputs_hash
                and event["payload"].get("status") in {"passed", "partial", "cached"}
            ),
            None,
        )
        if previous and store.list_nodes(case_id):
            cached = {
                **previous,
                "status": "cached",
                "cache_hit": True,
                "high_cost_parser_reexecuted": False,
            }
            store.audit(
                case_id, RECONSTRUCTION_EVENT, cached, "case_service"
            )
            return cached

        extractor = None if selected_mode is WorkflowMode.LOCAL_VLLM else (
            EmptyMockEvidenceExtractor()
        )
        summary = EvidenceReconstructionPipeline(
            self.workspace, extractor=extractor
        ).reconstruct(case_id)
        payload = {
            **summary.to_dict(),
            "inputs_hash": inputs_hash,
            "mode": selected_mode.value,
            "cache_hit": False,
            "high_cost_parser_reexecuted": True,
        }
        store.audit(case_id, RECONSTRUCTION_EVENT, payload, "case_service")
        return payload

    def source_inputs_hash(self, case_id: str) -> str:
        sources = self.workspace.store(case_id).list_sources(case_id)
        encoded = "\n".join(
            f"{item.source_id}:{item.sha256}:{item.role.value}"
            for item in sorted(sources, key=lambda item: item.source_id)
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
