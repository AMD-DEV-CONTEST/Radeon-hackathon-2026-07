from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from policyseal.application.matrix import evaluate_xlsx
from policyseal.application.state_machine import transition_status
from policyseal.audit.chain import AuditChain
from policyseal.audit.models import AuditEventType
from policyseal.documents.base import (
    CapabilityFinding,
    DocumentAdapter,
    ParsedDocument,
    PreflightDisposition,
)
from policyseal.domain.enums import (
    Action,
    ContentCategory,
    DecisionOrigin,
    FileKind,
    RevisionStatus,
)
from policyseal.domain.errors import AnalysisFailed, ResidualOutputError, UnsafeOutputError
from policyseal.domain.models import (
    DisclosureContext,
    DisclosureRevision,
    DisclosureTask,
    DocumentRegion,
    PolicyDecision,
    RevisionStageEvent,
    SourceFingerprint,
    StoredArtifactRecord,
)
from policyseal.policy.evaluator import evaluate_region
from policyseal.policy.schema import PolicyPack
from policyseal.security.fingerprints import KeyedFingerprinter
from policyseal.storage.file_store import ControlledFileStore, FileNamespace
from policyseal.storage.repositories import PolicySealRepository


class SemanticClassificationPort(Protocol):
    def classify_regions(
        self,
        regions: tuple[DocumentRegion, ...],
    ) -> tuple[DocumentRegion, ...]: ...


class PreserveUncertaintyClassifier:
    def classify_regions(
        self,
        regions: tuple[DocumentRegion, ...],
    ) -> tuple[DocumentRegion, ...]:
        return regions


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    task: DisclosureTask
    revision: DisclosureRevision
    regions: tuple[DocumentRegion, ...]
    decisions: tuple[PolicyDecision, ...]
    events: tuple[RevisionStageEvent, ...]
    preview_storage_ids: tuple[str, ...] = ()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _default_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _manifest_sha256(decisions: tuple[PolicyDecision, ...]) -> str:
    payload = [
        {
            "action": decision.action.value,
            "category": decision.category.value,
            "evidence_ids": decision.evidence_ids,
            "origin": decision.origin.value,
            "policy_sha256": decision.policy_sha256,
            "policy_version": decision.policy_version,
            "reason_code": decision.reason_code,
            "region_id": decision.region_id,
            "rule_ids": decision.rule_ids,
            "transform": decision.transform,
        }
        for decision in decisions
    ]
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


_PREFLIGHT_RULES: dict[
    str,
    tuple[ContentCategory, str, tuple[str, ...]],
] = {
    "xlsx_formula_unsupported": (
        ContentCategory.INTERNAL_COST_BUDGET,
        "PS-PREFLIGHT-XLSX-FORMULA",
        ("EV-GEN-002",),
    ),
    "docx_embedded_content": (
        ContentCategory.UNCLASSIFIED,
        "PS-PREFLIGHT-DOCX-EMBEDDED",
        ("EV-GEN-002",),
    ),
    "pdf_embedded_file": (
        ContentCategory.SOURCE_METADATA,
        "PS-PREFLIGHT-PDF-ATTACHMENT",
        ("EV-PDF-004", "EV-GEN-002"),
    ),
    "pdf_unextractable_page": (
        ContentCategory.UNCLASSIFIED,
        "PS-PREFLIGHT-PDF-OCR",
        ("EV-GEN-002",),
    ),
}


def _system_region_id(source_sha256: str, location: str, reason_code: str) -> str:
    payload = f"{source_sha256}\0{location}\0{reason_code}".encode()
    return f"system-{hashlib.sha256(payload).hexdigest()[:24]}"


def _preflight_records(
    pack: PolicyPack,
    source_sha256: str,
    file_kind: FileKind,
    findings: tuple[CapabilityFinding, ...],
) -> tuple[tuple[DocumentRegion, ...], tuple[PolicyDecision, ...]]:
    records: list[tuple[DocumentRegion, PolicyDecision]] = []
    for order, finding in enumerate(findings):
        if finding.disposition is not PreflightDisposition.BLOCK:
            continue
        category, rule_id, evidence_ids = _PREFLIGHT_RULES.get(
            finding.code,
            (
                ContentCategory.UNCLASSIFIED,
                "PS-PREFLIGHT-BLOCK",
                ("EV-GEN-002",),
            ),
        )
        region_id = _system_region_id(source_sha256, finding.location, finding.code)
        region = DocumentRegion(
            id=region_id,
            file_kind=file_kind,
            location=finding.location,
            order=order,
            text=finding.code,
            category=category,
        )
        decision = PolicyDecision(
            region_id=region_id,
            category=category,
            action=Action.BLOCK,
            rule_ids=(rule_id,),
            evidence_ids=evidence_ids,
            reason_code=finding.code,
            reason=finding.message,
            policy_version=pack.version,
            policy_sha256=pack.sha256,
            origin=DecisionOrigin.FAIL_CLOSED,
        )
        records.append((region, decision))
    return (
        tuple(item[0] for item in records),
        tuple(item[1] for item in records),
    )


def _output_block_record(
    pack: PolicyPack,
    source_sha256: str,
    file_kind: FileKind,
    *,
    category: ContentCategory,
    location: str,
    rule_id: str,
    evidence_ids: tuple[str, ...],
    reason_code: str,
    reason: str,
    order: int,
) -> tuple[DocumentRegion, PolicyDecision]:
    region_id = _system_region_id(source_sha256, location, reason_code)
    region = DocumentRegion(
        id=region_id,
        file_kind=file_kind,
        location=location,
        order=order,
        text=reason_code,
        category=category,
    )
    decision = PolicyDecision(
        region_id=region_id,
        category=category,
        action=Action.BLOCK,
        rule_ids=(rule_id,),
        evidence_ids=evidence_ids,
        reason_code=reason_code,
        reason=reason,
        policy_version=pack.version,
        policy_sha256=pack.sha256,
        origin=DecisionOrigin.FAIL_CLOSED,
    )
    return region, decision


class AnalysisService:
    def __init__(
        self,
        repository: PolicySealRepository,
        file_store: ControlledFileStore,
        policy_pack: PolicyPack,
        adapters: Mapping[FileKind, DocumentAdapter],
        fingerprinter: KeyedFingerprinter,
        *,
        semantic_classifier: SemanticClassificationPort | None = None,
        audit_chain: AuditChain | None = None,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[str], str] = _default_id,
    ) -> None:
        self.repository = repository
        self.file_store = file_store
        self.policy_pack = policy_pack
        self.adapters = dict(adapters)
        self.fingerprinter = fingerprinter
        self.semantic_classifier = semantic_classifier or PreserveUncertaintyClassifier()
        self._clock = clock
        self._id_factory = id_factory
        self.audit_chain = audit_chain or AuditChain.restore(
            repository.list_audit_events(),
            clock=clock,
        )

    def create_task(
        self,
        source_bytes: bytes,
        *,
        suffix: str,
        context: DisclosureContext,
        requester_id: str,
    ) -> AnalysisResult:
        file_kind = self._file_kind(suffix)
        if context.policy_version != self.policy_pack.definition.version:
            raise AnalysisFailed("requested policy version is unavailable")
        if not source_bytes or not requester_id.strip():
            raise AnalysisFailed("source bytes and requester are required")
        stored = self.file_store.write(FileNamespace.SOURCES, source_bytes, suffix=suffix)
        now = self._now()
        task = DisclosureTask(
            id=self._id_factory("task"),
            requester_id=requester_id,
            file_kind=file_kind,
            source=SourceFingerprint(stored.sha256, stored.size_bytes),
            source_storage_id=stored.storage_id,
            created_at=now,
        )
        revision = DisclosureRevision(
            id=self._id_factory("revision"),
            task_id=task.id,
            revision_number=1,
            requester_id=requester_id,
            context=context,
            status=RevisionStatus.DRAFT,
            source_sha256=task.source.sha256,
            policy_sha256=self.policy_pack.sha256,
            created_at=now,
        )
        try:
            self.repository.add_task(task)
            self.repository.add_revision(revision)
        except Exception:
            self.file_store.delete(FileNamespace.SOURCES, stored.storage_id)
            raise
        self._stage(revision.id, "revision_created", RevisionStatus.DRAFT.value)
        requester_hmac = self.fingerprinter.digest("requester", requester_id, scope=task.id)
        self._audit(
            AuditEventType.TASK_CREATED,
            {
                "task_id": task.id,
                "source_sha256": task.source.sha256,
                "file_kind": task.file_kind.value,
                "classification": context.classification.value,
                "requester_hmac": requester_hmac,
            },
            actor="system",
            task_id=task.id,
            revision_id=None,
        )
        self._audit(
            AuditEventType.REVISION_CREATED,
            {
                "revision_id": revision.id,
                "revision_number": revision.revision_number,
                "source_sha256": revision.source_sha256,
                "context_sha256": context.sha256,
                "status": revision.status.value,
            },
            actor="system",
            task_id=task.id,
            revision_id=revision.id,
        )
        return AnalysisResult(
            task,
            revision,
            (),
            (),
            self.repository.list_stage_events(revision.id),
        )

    def create_revision(
        self,
        task_id: str,
        *,
        context: DisclosureContext,
        actor: str,
    ) -> AnalysisResult:
        task = self.repository.get_task(task_id)
        if actor != task.requester_id:
            raise AnalysisFailed("only the task requester can create a formal revision")
        if context.policy_version != self.policy_pack.definition.version:
            raise AnalysisFailed("requested policy version is unavailable")
        revisions = self.repository.list_revisions(task_id)
        revision = DisclosureRevision(
            id=self._id_factory("revision"),
            task_id=task.id,
            revision_number=len(revisions) + 1,
            requester_id=task.requester_id,
            context=context,
            status=RevisionStatus.DRAFT,
            source_sha256=task.source.sha256,
            policy_sha256=self.policy_pack.sha256,
            created_at=self._now(),
        )
        self.repository.add_revision(revision)
        self._stage(revision.id, "revision_created", revision.status.value)
        self._audit(
            AuditEventType.CONTEXT_CHANGED,
            {
                "context_sha256": context.sha256,
                "recipient": context.recipient.value,
                "purpose": context.purpose.value,
                "channel": context.channel.value,
                "classification": context.classification.value,
                "policy_version": context.policy_version,
            },
            actor=actor,
            task_id=task.id,
            revision_id=revision.id,
        )
        return AnalysisResult(
            task,
            revision,
            (),
            (),
            self.repository.list_stage_events(revision.id),
        )

    def analyze_revision(self, revision_id: str) -> AnalysisResult:
        revision = self.repository.get_revision(revision_id)
        task = self.repository.get_task(revision.task_id)
        transition_status(revision.status, RevisionStatus.ANALYZING)
        revision = self.repository.transition_revision_status(
            revision.id,
            expected=revision.status,
            target=RevisionStatus.ANALYZING,
        )
        self._stage(revision.id, "analysis", "started")
        self._audit(
            AuditEventType.ANALYSIS_STARTED,
            {"revision_id": revision.id, "region_count": 0, "status": revision.status.value},
            actor="system",
            task_id=task.id,
            revision_id=revision.id,
        )

        source_path = self.file_store.path_for(FileNamespace.SOURCES, task.source_storage_id)
        adapter = self.adapters[task.file_kind]
        parsed: ParsedDocument | None = None
        regions: tuple[DocumentRegion, ...] = ()
        decisions: tuple[PolicyDecision, ...] = ()
        output_storage_id: str | None = None
        output_sha256: str | None = None
        preview_ids: tuple[str, ...] = ()
        try:
            self._stage(revision.id, "preflight", "started")
            preflight = adapter.preflight(source_path)
            self._stage(revision.id, "preflight", preflight.disposition.value)
            if preflight.blocked:
                terminal = (
                    RevisionStatus.PROCESSING_FAILED
                    if preflight.disposition is PreflightDisposition.PROCESSING_FAILED
                    else RevisionStatus.BLOCKED
                )
                if terminal is RevisionStatus.BLOCKED:
                    regions, decisions = _preflight_records(
                        self.policy_pack,
                        task.source.sha256,
                        task.file_kind,
                        preflight.findings,
                    )
                return self._complete(
                    task,
                    revision,
                    terminal,
                    regions,
                    decisions,
                    None,
                    None,
                    preview_ids,
                )

            self._stage(revision.id, "parse", "started")
            parsed = adapter.parse(source_path)
            regions = parsed.regions
            self._stage(revision.id, "parse", "completed")
            preview_ids = self._store_previews(task, revision, adapter, source_path)

            self._stage(revision.id, "deterministic_scan", "started")
            self._stage(revision.id, "deterministic_scan", "completed")

            self._stage(revision.id, "semantic_classification", "started")
            classified = self.semantic_classifier.classify_regions(regions)
            if tuple(region.id for region in classified) != tuple(region.id for region in regions):
                raise AnalysisFailed("semantic classification changed stable region identities")
            regions = classified
            parsed = replace(parsed, regions=regions)
            self._stage(revision.id, "semantic_classification", "completed")

            self._stage(revision.id, "policy_evaluation", "started")
            decisions = self._evaluate(parsed, revision.context)
            self._stage(revision.id, "policy_evaluation", "completed")

            if any(decision.action is Action.BLOCK for decision in decisions):
                terminal = RevisionStatus.BLOCKED
            elif (
                preflight.disposition is PreflightDisposition.REQUIRE_CONFIRMATION
                and not any(
                    decision.action is Action.REQUIRE_APPROVAL for decision in decisions
                )
            ):
                terminal = RevisionStatus.AWAITING_CONFIRMATION
            else:
                self._stage(revision.id, "render", "started")
                with tempfile.TemporaryDirectory(prefix="policyseal-render-") as directory:
                    rendered = adapter.render(parsed, decisions, Path(directory))
                    self._stage(revision.id, "output_validation", "passed")
                    self._stage(revision.id, "residual_check", "passed")
                    output_bytes = rendered.output_path.read_bytes()
                    stored = self.file_store.write(
                        FileNamespace.OUTPUTS,
                        output_bytes,
                        suffix=rendered.output_path.suffix,
                    )
                output_storage_id = stored.storage_id
                output_sha256 = stored.sha256
                self._stage(revision.id, "render", "validated")
                terminal = (
                    RevisionStatus.AWAITING_APPROVAL
                    if any(decision.action is Action.REQUIRE_APPROVAL for decision in decisions)
                    else RevisionStatus.EXPORTABLE
                )
            return self._complete(
                task,
                revision,
                terminal,
                regions,
                decisions,
                output_storage_id,
                output_sha256,
                preview_ids,
            )
        except ResidualOutputError as error:
            if output_storage_id is not None:
                self.file_store.delete(FileNamespace.OUTPUTS, output_storage_id)
            self._stage(revision.id, "residual_check", "blocked")
            region, decision = _output_block_record(
                self.policy_pack,
                task.source.sha256,
                task.file_kind,
                category=error.category,
                location=error.location,
                rule_id=error.rule_id,
                evidence_ids=error.evidence_ids,
                reason_code="residual_risk_detected",
                reason=str(error),
                order=len(regions),
            )
            return self._complete(
                task,
                revision,
                RevisionStatus.BLOCKED,
                regions + (region,),
                decisions + (decision,),
                None,
                None,
                preview_ids,
            )
        except UnsafeOutputError:
            if output_storage_id is not None:
                self.file_store.delete(FileNamespace.OUTPUTS, output_storage_id)
            self._stage(revision.id, "output_validation", "blocked")
            region, decision = _output_block_record(
                self.policy_pack,
                task.source.sha256,
                task.file_kind,
                category=ContentCategory.UNCLASSIFIED,
                location="output:validation",
                rule_id="PS-RESIDUAL-VALIDATION",
                evidence_ids=("EV-GEN-002",),
                reason_code="output_validation_failed",
                reason="Mandatory output validation could not prove the generated file safe.",
                order=len(regions),
            )
            return self._complete(
                task,
                revision,
                RevisionStatus.BLOCKED,
                regions + (region,),
                decisions + (decision,),
                None,
                None,
                preview_ids,
            )
        except Exception as error:
            if output_storage_id is not None:
                self.file_store.delete(FileNamespace.OUTPUTS, output_storage_id)
            try:
                self._complete(
                    task,
                    revision,
                    RevisionStatus.PROCESSING_FAILED,
                    regions,
                    (),
                    None,
                    None,
                    preview_ids,
                    reason_code="controlled_analysis_failure",
                )
            except Exception as persistence_error:
                raise AnalysisFailed(
                    "analysis and failure persistence both failed"
                ) from persistence_error
            if isinstance(error, AnalysisFailed):
                raise
            raise AnalysisFailed("revision reached a controlled processing failure") from error
        finally:
            del parsed

    def get_result(self, revision_id: str) -> AnalysisResult:
        revision = self.repository.get_revision(revision_id)
        task = self.repository.get_task(revision.task_id)
        return AnalysisResult(
            task=task,
            revision=revision,
            regions=self.repository.list_regions(revision_id),
            decisions=self.repository.list_decisions(revision_id),
            events=self.repository.list_stage_events(revision_id),
        )

    def _complete(
        self,
        task: DisclosureTask,
        revision: DisclosureRevision,
        status: RevisionStatus,
        regions: tuple[DocumentRegion, ...],
        decisions: tuple[PolicyDecision, ...],
        output_storage_id: str | None,
        output_sha256: str | None,
        preview_ids: tuple[str, ...],
        *,
        reason_code: str | None = None,
    ) -> AnalysisResult:
        transition_status(RevisionStatus.ANALYZING, status)
        manifest_sha256 = _manifest_sha256(decisions)
        completed = self.repository.complete_analysis(
            revision.id,
            status=status,
            regions=regions,
            decisions=decisions,
            output_storage_id=output_storage_id,
            output_sha256=output_sha256,
            decision_manifest_sha256=manifest_sha256,
        )
        self._stage(revision.id, "analysis", status.value)
        if status is RevisionStatus.PROCESSING_FAILED:
            self._audit(
                AuditEventType.ANALYSIS_FAILED,
                {
                    "revision_id": revision.id,
                    "reason_code": reason_code or "processing_failed",
                    "status": status.value,
                },
                actor="system",
                task_id=task.id,
                revision_id=revision.id,
            )
        else:
            self._audit(
                AuditEventType.ANALYSIS_COMPLETED,
                {
                    "revision_id": revision.id,
                    "region_count": len(regions),
                    "decision_count": len(decisions),
                    "output_sha256": output_sha256 or "0" * 64,
                    "status": status.value,
                },
                actor="system",
                task_id=task.id,
                revision_id=revision.id,
            )
        return AnalysisResult(
            task,
            completed,
            regions,
            decisions,
            self.repository.list_stage_events(revision.id),
            preview_ids,
        )

    def _store_previews(
        self,
        task: DisclosureTask,
        revision: DisclosureRevision,
        adapter: DocumentAdapter,
        source_path: Path,
    ) -> tuple[str, ...]:
        stored_ids: list[str] = []
        with tempfile.TemporaryDirectory(prefix="policyseal-preview-") as directory:
            for preview in adapter.preview(source_path, Path(directory)):
                stored = self.file_store.write(
                    FileNamespace.PREVIEWS,
                    preview.path.read_bytes(),
                    suffix=preview.path.suffix,
                )
                self.repository.add_artifact(
                    StoredArtifactRecord(
                        task.id,
                        revision.id,
                        FileNamespace.PREVIEWS.value,
                        stored.storage_id,
                    )
                )
                stored_ids.append(stored.storage_id)
        return tuple(stored_ids)

    def _evaluate(
        self,
        parsed: ParsedDocument,
        context: DisclosureContext,
    ) -> tuple[PolicyDecision, ...]:
        if parsed.file_kind is FileKind.XLSX:
            return evaluate_xlsx(parsed, self.policy_pack, context)
        return tuple(
            evaluate_region(self.policy_pack, context, region) for region in parsed.regions
        )

    def _stage(self, revision_id: str, stage: str, status: str) -> RevisionStageEvent:
        return self.repository.append_stage_event(
            revision_id,
            stage=stage,
            status=status,
            occurred_at=self._now(),
        )

    def _audit(
        self,
        event_type: AuditEventType,
        payload: Mapping[str, object],
        *,
        actor: str,
        task_id: str,
        revision_id: str | None,
    ) -> None:
        event = self.audit_chain.append(
            event_type,
            payload,
            actor=actor,
            task_id=task_id,
            revision_id=revision_id,
            policy_sha256=self.policy_pack.sha256,
        )
        try:
            self.repository.append_audit_event(event)
        except Exception:
            self.audit_chain._events.pop()  # noqa: SLF001
            raise

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise AnalysisFailed("application clock must be timezone aware")
        return value.astimezone(UTC)

    @staticmethod
    def _file_kind(suffix: str) -> FileKind:
        try:
            return {".xlsx": FileKind.XLSX, ".docx": FileKind.DOCX, ".pdf": FileKind.PDF}[
                suffix.casefold()
            ]
        except KeyError as error:
            raise AnalysisFailed("P0 supports only XLSX, DOCX, and PDF") from error


__all__ = ["AnalysisResult", "AnalysisService", "PreserveUncertaintyClassifier"]
