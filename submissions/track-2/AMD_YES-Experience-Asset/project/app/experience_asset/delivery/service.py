"""E7 application service for canonical drafts, deterministic export, and deletion."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.experience_asset.domain.enums import (
    ExportFormat,
    ExportState,
    PrivacyResolution,
    RouteEligibility,
    RouteType,
)
from app.experience_asset.domain.models import (
    ApprovalRecord,
    ExperienceAssetV1,
    ExportRecord,
    PrivacyFinding,
    RouteDecision,
    RouteDraft,
)
from app.experience_asset.renderers import DeterministicDeliveryRenderer

from .approval import ApprovalRejectedError, ApprovalValidator
from .filesystem import ArtifactStore, ArtifactStoreError, sha256_bytes
from .models import (
    DeletionItemState,
    DeletionJobState,
    DeletionOutcomeV1,
    DeletionRequestState,
    DeletionRequestV1,
    DeliveryOperation,
    DraftState,
    ExportBundleResultV1,
    ExportRequestState,
    RenderBundleV1,
    RouteDraftContentV1,
    StoredRouteDraftV1,
    route_draft_content_hash,
)
from .repository import (
    DeletionJobSnapshot,
    DeliveryConflictError,
    DeliveryPersistenceError,
    E7DeliveryRepository,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RouteDraftContractError(ValueError):
    pass


class RouteIneligibleError(RouteDraftContractError):
    pass


class SecondConfirmationRequiredError(PermissionError):
    pass


def canonical_asset_hash(asset: ExperienceAssetV1) -> str:
    """Match the existing snapshot repository's canonical byte/hash calculation."""

    return hashlib.sha256(asset.model_dump_json().encode("utf-8")).hexdigest()


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class E7DeliveryService:
    def __init__(
        self,
        repository: E7DeliveryRepository,
        artifact_store: ArtifactStore,
        approval_validator: ApprovalValidator,
        renderer: DeterministicDeliveryRenderer | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.approval_validator = approval_validator
        self.renderer = renderer or DeterministicDeliveryRenderer()

    @staticmethod
    def _privacy_binding(
        findings: list[PrivacyFinding],
    ) -> tuple[str, dict[str, PrivacyResolution]]:
        findings = sorted(findings, key=lambda finding: str(finding.finding_id))
        resolutions = {str(finding.finding_id): finding.resolution for finding in findings}
        payload = [
            {
                "finding_id": str(finding.finding_id),
                "category": finding.category,
                "severity": finding.severity.value,
                "affected_statement_ids": sorted(
                    str(value) for value in finding.affected_statement_ids
                ),
                "affected_source_ids": sorted(str(value) for value in finding.affected_source_ids),
                "resolution": finding.resolution.value,
            }
            for finding in findings
        ]
        return _canonical_hash(payload), resolutions

    @staticmethod
    def _route_decision(
        asset: ExperienceAssetV1,
        route: RouteType,
        decisions: list[RouteDecision],
    ):
        decision = next((item for item in decisions if item.route is route), None)
        if decision is None:
            raise RouteDraftContractError("selected route has no RouteDecision")
        if decision.canonical_version_id != asset.version_id:
            raise RouteDraftContractError("RouteDecision is not bound to the current version")
        if decision.eligibility in {RouteEligibility.INELIGIBLE, RouteEligibility.BLOCKED}:
            raise RouteIneligibleError(
                f"route {route.value} is {decision.eligibility.value}: "
                f"{','.join(decision.reason_codes)}"
            )
        return decision

    @staticmethod
    def _validate_content(
        asset: ExperienceAssetV1,
        content: RouteDraftContentV1,
        decision: RouteDecision,
    ) -> None:
        known = {statement.statement_id for statement in asset.statements}
        referenced = set(content.all_statement_ids())
        if not referenced:
            raise RouteDraftContractError("route draft content requires canonical statement links")
        if not referenced.issubset(known):
            raise RouteDraftContractError("route draft content references unknown statements")
        if not referenced.issubset(set(decision.supporting_statement_ids)):
            raise RouteDraftContractError(
                "route draft content references statements outside the selected route evidence"
            )

    def save_route_draft(
        self,
        *,
        create_request_id: UUID,
        asset: ExperienceAssetV1,
        asset_version_hash: str,
        relation_projection_hash: str,
        route: RouteType,
        language: str,
        content: RouteDraftContentV1,
        created_by_run_id: UUID,
        route_decisions: list[RouteDecision] | None = None,
        privacy_findings: list[PrivacyFinding] | None = None,
        now: datetime | None = None,
        route_draft_id: UUID | None = None,
    ) -> StoredRouteDraftV1:
        if language not in {"zh-CN", "en"}:
            raise RouteDraftContractError("one draft must select exactly zh-CN or en")
        if not _SHA256.fullmatch(asset_version_hash):
            raise RouteDraftContractError("asset_version_hash must be an exact SHA-256")
        if asset_version_hash != canonical_asset_hash(asset):
            raise RouteDraftContractError(
                "asset_version_hash does not match the canonical ExperienceAsset bytes"
            )
        if not _SHA256.fullmatch(relation_projection_hash):
            raise RouteDraftContractError("relation_projection_hash must be an exact SHA-256")
        decision = self._route_decision(
            asset,
            route,
            route_decisions if route_decisions is not None else asset.route_decisions,
        )
        self._validate_content(asset, content, decision)
        privacy_state_hash, resolutions = self._privacy_binding(
            privacy_findings if privacy_findings is not None else asset.privacy_findings
        )
        renderer_input = {
            "schema_version": "e7-renderer-input/v1",
            "asset_id": str(asset.asset_id),
            "asset_version_id": str(asset.version_id),
            "asset_version_hash": asset_version_hash,
            "lineage": {
                "version_id": str(asset.lineage.version_id),
                "parent_version_id": (
                    str(asset.lineage.parent_version_id)
                    if asset.lineage.parent_version_id
                    else None
                ),
            },
            "relation_projection_hash": relation_projection_hash,
            "route_decision": decision.model_dump(mode="json"),
            "language": language,
            "privacy_state_hash": privacy_state_hash,
            "privacy_finding_resolutions": {
                key: value.value for key, value in sorted(resolutions.items())
            },
            "content": content.model_dump(mode="json"),
        }
        renderer_input_identity = _canonical_hash(renderer_input)
        draft_content_hash = route_draft_content_hash(content)
        existing = self.repository.get_draft_by_request(create_request_id)
        if existing:
            if existing.renderer_input_identity != renderer_input_identity:
                raise DeliveryConflictError("draft request identity already has other inputs")
            return existing
        created = now or datetime.now(UTC)
        draft = RouteDraft(
            route_draft_id=route_draft_id or uuid4(),
            route=route,
            language=language,
            canonical_version_id=asset.version_id,
            statement_ids=content.all_statement_ids(),
            content_hash=draft_content_hash,
            created_by_run_id=created_by_run_id,
        )
        stored = StoredRouteDraftV1(
            create_request_id=create_request_id,
            asset_id=asset.asset_id,
            asset_version_hash=asset_version_hash,
            lineage_version_id=asset.lineage.version_id,
            lineage_parent_version_id=asset.lineage.parent_version_id,
            relation_projection_hash=relation_projection_hash,
            privacy_state_hash=privacy_state_hash,
            privacy_finding_resolutions=resolutions,
            renderer_input_identity=renderer_input_identity,
            draft=draft,
            content=content,
            created_at=created,
            updated_at=created,
        )
        return self.repository.save_draft(stored)

    def preview(self, draft_id: UUID) -> RenderBundleV1:
        """Private preview is deliberately independent of external approval."""

        draft = self.repository.get_draft(draft_id)
        return self.renderer.render(draft, operation=DeliveryOperation.IN_APP_PREVIEW)

    def export_bundle(
        self,
        *,
        request_id: UUID,
        draft_id: UUID,
        operation: DeliveryOperation,
        approval: ApprovalRecord | None = None,
        now: datetime | None = None,
    ) -> ExportBundleResultV1:
        if operation is DeliveryOperation.IN_APP_PREVIEW:
            raise RouteDraftContractError("preview is not a file-export operation")
        created = now or datetime.now(UTC)
        draft = self.repository.get_draft(draft_id)
        if draft.state is not DraftState.CURRENT:
            raise DeliveryConflictError("a superseded draft cannot create current exports")
        approval_id = None
        if operation is DeliveryOperation.PRIVATE_DOWNLOAD:
            if draft.draft.route is not RouteType.PRIVATE_SELF:
                raise ApprovalRejectedError(
                    "PRIVATE_DOWNLOAD_ROUTE_MISMATCH",
                    "Private download is limited to the private/self route.",
                )
        else:
            if draft.draft.route is RouteType.PRIVATE_SELF:
                raise ApprovalRejectedError(
                    "EXTERNAL_ROUTE_REQUIRED",
                    "Use an external-audience route for a shareable export.",
                )
            try:
                validated = self.approval_validator.validate_external_export(draft, approval)
            except ApprovalRejectedError as exc:
                self.repository.record_failure_best_effort(
                    asset_id=draft.asset_id,
                    request_id=request_id,
                    event_type="EXPORT_POLICY_BLOCKED",
                    state="POLICY_BLOCKED",
                    code=exc.code,
                    now=created,
                )
                raise
            approval_id = validated.approval_id
        rendered = self.renderer.render(
            draft,
            operation=operation,
            approval_id=approval_id,
        )
        payloads = {
            ExportFormat.HTML: rendered.html.encode("utf-8"),
            ExportFormat.MARKDOWN: rendered.markdown.encode("utf-8"),
            ExportFormat.JSON: rendered.canonical_json.encode("utf-8"),
        }
        planned = [
            ExportRecord(
                export_id=uuid5(NAMESPACE_URL, f"e7:{request_id}:{format.value}"),
                asset_id=draft.asset_id,
                version_id=draft.draft.canonical_version_id,
                route=draft.draft.route,
                route_draft_hash=draft.draft.content_hash,
                format=format,
                file_hash=sha256_bytes(data),
                path=self.artifact_store.path_for(
                    asset_id=draft.asset_id,
                    draft_id=draft.draft.route_draft_id,
                    request_id=request_id,
                    format=format,
                ),
                created_at=created,
                state=ExportState.FAILED,
            )
            for format, data in payloads.items()
        ]
        request = self.repository.prepare_export(
            request_id=request_id,
            draft=draft,
            operation=operation,
            approval_id=approval_id,
            records=planned,
            now=created,
        )
        if {(record.format, record.file_hash, record.path) for record in request.records} != {
            (record.format, record.file_hash, record.path) for record in planned
        }:
            raise DeliveryConflictError("persisted export request differs from deterministic bytes")

        failures: list[ExportFormat] = []
        for record in request.records:
            data = payloads[record.format]
            try:
                if self.artifact_store.exists(record.path):
                    if sha256_bytes(self.artifact_store.read(record.path)) != record.file_hash:
                        raise ArtifactStoreError(
                            "EXISTING_FILE_HASH_MISMATCH",
                            "Managed export bytes do not match their persisted hash.",
                        )
                else:
                    self.artifact_store.write(record.path, data)
                self.repository.mark_export_written(record.export_id, now=created)
            except ArtifactStoreError as exc:
                failures.append(record.format)
                self.repository.mark_export_failed(
                    record.export_id,
                    code=exc.code,
                    now=created,
                )
        state = ExportRequestState.FAILED if failures else ExportRequestState.COMPLETE
        snapshot = self.repository.finish_export_request(
            request_id,
            state=state,
            error_code="FILESYSTEM_WRITE_FAILED" if failures else None,
            now=created,
        )
        return ExportBundleResultV1(
            request_id=request_id,
            route_draft_id=draft.draft.route_draft_id,
            operation=operation,
            state=snapshot.state,
            records=snapshot.records,
            failed_formats=sorted(failures, key=lambda item: item.value),
            error_code=snapshot.error_code,
            retryable=bool(failures),
        )

    def request_deletion(
        self,
        *,
        request_id: UUID,
        asset_id: UUID,
        now: datetime | None = None,
        expires_in: timedelta = timedelta(minutes=15),
    ) -> DeletionRequestV1:
        created = now or datetime.now(UTC)
        token = f"DELETE-{request_id.hex[:12].upper()}"
        request = DeletionRequestV1(
            request_id=request_id,
            asset_id=asset_id,
            state=DeletionRequestState.REQUESTED,
            confirmation_token=token,
            created_at=created,
            expires_at=created + expires_in,
        )
        return self.repository.create_deletion_request(request)

    def confirm_deletion(
        self,
        *,
        request_id: UUID,
        confirmation_token: str,
        second_confirmation: bool,
        now: datetime | None = None,
    ) -> DeletionOutcomeV1:
        current = now or datetime.now(UTC)
        request = self.repository.get_deletion_request(request_id)
        if request.state is DeletionRequestState.COMPLETED:
            return self._outcome(self.repository.get_deletion_job(request_id))
        if not second_confirmation:
            raise SecondConfirmationRequiredError(
                "Deletion requires a separate, explicit second confirmation."
            )
        job_id = request.job_id or uuid5(NAMESPACE_URL, f"e7-deletion:{request_id}")
        try:
            job = self.repository.begin_deletion(
                request_id,
                confirmation_token=confirmation_token,
                now=current,
                job_id=job_id,
            )
        except DeliveryConflictError:
            raise
        except DeliveryPersistenceError:
            self.repository.record_failure_best_effort(
                asset_id=request.asset_id,
                request_id=request_id,
                event_type="DELETION_STORAGE_FAILURE",
                state="STORAGE_ERROR",
                code="SQLITE_BEGIN_FAILED",
                now=current,
            )
            return DeletionOutcomeV1(
                request_id=request_id,
                asset_id=request.asset_id,
                state="STORAGE_ERROR",
                terminal_state="STORAGE_ERROR",
                retryable=True,
                deleted_file_count=0,
                deleted_draft_count=0,
                deleted_export_count=0,
                safe_user_message=(
                    "Deletion did not start because durable storage failed; no files were removed."
                ),
            )
        return self._resume_job(job, now=current)

    def retry_deletion(
        self,
        request_id: UUID,
        *,
        now: datetime | None = None,
    ) -> DeletionOutcomeV1:
        current = now or datetime.now(UTC)
        request = self.repository.get_deletion_request(request_id)
        if request.state is DeletionRequestState.REQUESTED:
            raise SecondConfirmationRequiredError(
                "Deletion has not received its second confirmation."
            )
        if request.state is DeletionRequestState.EXPIRED:
            raise DeliveryConflictError("deletion request expired before confirmation")
        return self._resume_job(self.repository.get_deletion_job(request_id), now=current)

    def _resume_job(self, job: DeletionJobSnapshot, *, now: datetime) -> DeletionOutcomeV1:
        if job.state is DeletionJobState.COMPLETED:
            return self._outcome(job)
        failures: list[str] = []
        if job.state is not DeletionJobState.FILES_REMOVED:
            for item in job.items:
                if item.state is DeletionItemState.DELETED:
                    continue
                try:
                    self.artifact_store.delete(item.path)
                    if self.artifact_store.exists(item.path):
                        raise ArtifactStoreError(
                            "FILESYSTEM_DELETE_UNVERIFIED",
                            "Managed export still exists after deletion.",
                        )
                    self.repository.mark_deletion_item(
                        job.job_id,
                        item.path,
                        state=DeletionItemState.DELETED,
                        error_code=None,
                        now=now,
                    )
                except ArtifactStoreError as exc:
                    failures.append(item.path)
                    try:
                        self.repository.mark_deletion_item(
                            job.job_id,
                            item.path,
                            state=DeletionItemState.FAILED,
                            error_code=exc.code,
                            now=now,
                        )
                    except DeliveryPersistenceError:
                        self.repository.record_failure_best_effort(
                            asset_id=job.asset_id,
                            request_id=job.request_id,
                            event_type="DELETION_STORAGE_FAILURE",
                            state="STORAGE_ERROR",
                            code="SQLITE_ITEM_FAILURE_UPDATE_FAILED",
                            now=now,
                        )
                        return self._storage_failure_outcome(
                            job,
                            "A file deletion failed and SQLite could not record it; retry is safe.",
                        )
                except DeliveryPersistenceError:
                    self.repository.record_failure_best_effort(
                        asset_id=job.asset_id,
                        request_id=job.request_id,
                        event_type="DELETION_STORAGE_FAILURE",
                        state="STORAGE_ERROR",
                        code="SQLITE_ITEM_UPDATE_FAILED",
                        now=now,
                    )
                    return self._storage_failure_outcome(
                        job,
                        "SQLite failed after a file effect; retry is safe.",
                    )
            if failures:
                try:
                    partial = self.repository.mark_deletion_job(
                        job.request_id,
                        state=DeletionJobState.PARTIAL_FAILURE,
                        terminal_state="DELETION_FAILED",
                        error_code="FILESYSTEM_DELETE_FAILED",
                        now=now,
                    )
                except DeliveryPersistenceError:
                    self.repository.record_failure_best_effort(
                        asset_id=job.asset_id,
                        request_id=job.request_id,
                        event_type="DELETION_STORAGE_FAILURE",
                        state="STORAGE_ERROR",
                        code="SQLITE_JOB_PARTIAL_UPDATE_FAILED",
                        now=now,
                    )
                    return self._storage_failure_outcome(
                        job,
                        "File deletion is incomplete and SQLite state update failed; "
                        "retry is safe.",
                    )
                return self._outcome(partial)
            try:
                job = self.repository.mark_deletion_job(
                    job.request_id,
                    state=DeletionJobState.FILES_REMOVED,
                    terminal_state=None,
                    error_code=None,
                    now=now,
                )
            except DeliveryPersistenceError:
                self.repository.record_failure_best_effort(
                    asset_id=job.asset_id,
                    request_id=job.request_id,
                    event_type="DELETION_STORAGE_FAILURE",
                    state="STORAGE_ERROR",
                    code="SQLITE_FILES_REMOVED_UPDATE_FAILED",
                    now=now,
                )
                return self._storage_failure_outcome(
                    job,
                    "Managed files are absent but SQLite state update failed; retry is safe.",
                )
        try:
            completed = self.repository.finalize_deletion(job.request_id, now=now)
        except DeliveryPersistenceError:
            self.repository.record_failure_best_effort(
                asset_id=job.asset_id,
                request_id=job.request_id,
                event_type="DELETION_STORAGE_FAILURE",
                state="FILES_REMOVED",
                code="SQLITE_FINALIZE_FAILED",
                now=now,
            )
            return self._storage_failure_outcome(
                job,
                "Managed files are absent but SQLite finalization failed; retry is safe.",
            )
        return self._outcome(completed)

    @staticmethod
    def _storage_failure_outcome(
        job: DeletionJobSnapshot,
        message: str,
    ) -> DeletionOutcomeV1:
        return DeletionOutcomeV1(
            request_id=job.request_id,
            asset_id=job.asset_id,
            job_id=job.job_id,
            state=(
                "FILES_REMOVED" if job.state is DeletionJobState.FILES_REMOVED else "STORAGE_ERROR"
            ),
            terminal_state="STORAGE_ERROR",
            retryable=True,
            deleted_file_count=sum(item.state is DeletionItemState.DELETED for item in job.items),
            deleted_draft_count=0,
            deleted_export_count=0,
            failed_paths=[
                item.path for item in job.items if item.state is DeletionItemState.FAILED
            ],
            safe_user_message=message,
        )

    @staticmethod
    def _outcome(job: DeletionJobSnapshot) -> DeletionOutcomeV1:
        completed = job.state is DeletionJobState.COMPLETED
        failed = [item.path for item in job.items if item.state is DeletionItemState.FAILED]
        deleted = sum(item.state is DeletionItemState.DELETED for item in job.items)
        if completed:
            message = "Deletion completed; all known product-managed E7 content and files are gone."
        else:
            message = (
                "Deletion is incomplete; the asset remains locked and the failed file steps "
                "can be retried."
            )
        return DeletionOutcomeV1(
            request_id=job.request_id,
            asset_id=job.asset_id,
            job_id=job.job_id,
            state=job.state.value,
            terminal_state=job.terminal_state or "DELETION_FAILED",
            retryable=not completed,
            deleted_file_count=deleted,
            deleted_draft_count=job.draft_count if completed else 0,
            deleted_export_count=job.export_count if completed else 0,
            failed_paths=failed,
            safe_user_message=message,
        )
