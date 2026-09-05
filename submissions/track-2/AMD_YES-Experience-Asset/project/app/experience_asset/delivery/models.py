"""E7-owned persisted envelopes around the frozen canonical delivery models."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.experience_asset.domain.enums import ExportFormat, PrivacyResolution, RouteType
from app.experience_asset.domain.models import (
    ApprovalRecord,
    ContractModel,
    ExportRecord,
    RouteDraft,
)

NonEmptyText = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DraftState(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"


class DeliveryOperation(StrEnum):
    IN_APP_PREVIEW = "IN_APP_PREVIEW"
    PRIVATE_DOWNLOAD = "PRIVATE_DOWNLOAD"
    SHAREABLE_EXTERNAL_EXPORT = "SHAREABLE_EXTERNAL_EXPORT"


class ExportRequestState(StrEnum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class DeletionRequestState(StrEnum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


class DeletionJobState(StrEnum):
    FILES_PENDING = "FILES_PENDING"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FILES_REMOVED = "FILES_REMOVED"
    COMPLETED = "COMPLETED"


class DeletionItemState(StrEnum):
    PENDING = "PENDING"
    DELETED = "DELETED"
    FAILED = "FAILED"


class DraftClaimV1(ContractModel):
    """One visible claim plus the canonical statements that support it."""

    text: NonEmptyText
    statement_ids: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def statement_ids_are_unique(self) -> DraftClaimV1:
        if len(self.statement_ids) != len(set(self.statement_ids)):
            raise ValueError("draft claim statement_ids must be unique")
        return self


class DraftSectionV1(ContractModel):
    heading: NonEmptyText
    claims: list[DraftClaimV1] = Field(min_length=1)


class RouteDraftContentV1(ContractModel):
    """The only stored content truth consumed by every E7 renderer."""

    title: NonEmptyText
    summary: DraftClaimV1
    sections: list[DraftSectionV1] = Field(min_length=1)
    notices: list[NonEmptyText] = Field(default_factory=list)

    def all_statement_ids(self) -> list[UUID]:
        values = [*self.summary.statement_ids]
        for section in self.sections:
            for claim in section.claims:
                values.extend(claim.statement_ids)
        return sorted(set(values), key=str)

    def all_claims(self) -> list[DraftClaimV1]:
        """Return every visible claim so one evidence rule guards every renderer."""

        return [
            self.summary,
            *(claim for section in self.sections for claim in section.claims),
        ]


def route_draft_content_hash(content: RouteDraftContentV1) -> str:
    """Hash only the editable canonical draft body, not renderer or approval inputs."""

    encoded = json.dumps(
        content.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StoredRouteDraftV1(ContractModel):
    """E7 persistence envelope; the nested RouteDraft remains the frozen domain contract."""

    schema_version: Literal["e7-route-draft/v1"] = "e7-route-draft/v1"
    create_request_id: UUID
    asset_id: UUID
    asset_version_hash: Sha256
    lineage_version_id: UUID
    lineage_parent_version_id: UUID | None = None
    relation_projection_hash: Sha256
    privacy_state_hash: Sha256
    privacy_finding_resolutions: dict[str, PrivacyResolution]
    renderer_input_identity: Sha256
    draft: RouteDraft
    content: RouteDraftContentV1
    state: DraftState = DraftState.CURRENT
    superseded_by_draft_id: UUID | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def exact_bindings_are_consistent(self) -> StoredRouteDraftV1:
        if self.draft.canonical_version_id != self.lineage_version_id:
            raise ValueError("route draft version must match lineage version")
        if self.draft.content_hash != route_draft_content_hash(self.content):
            raise ValueError("route draft content_hash must match the canonical draft body")
        if sorted(self.draft.statement_ids, key=str) != self.content.all_statement_ids():
            raise ValueError("route draft statement_ids must equal content claim bindings")
        if self.state is DraftState.CURRENT and self.superseded_by_draft_id is not None:
            raise ValueError("current draft cannot have a superseding draft")
        if self.state is DraftState.SUPERSEDED and self.superseded_by_draft_id is None:
            raise ValueError("superseded draft requires superseded_by_draft_id")
        return self


class FrozenE6ApprovalBindingV1(ContractModel):
    """One immutable E6-issued approval fixture bound to an exact E7 input snapshot."""

    schema_version: Literal["e6-e7-approval-binding/v1"] = "e6-e7-approval-binding/v1"
    fixture_id: NonEmptyText
    source_e6_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None = None
    route_draft_id: UUID
    asset_id: UUID
    version_id: UUID
    asset_version_hash: Sha256
    relation_projection_hash: Sha256
    route: RouteType
    language: Literal["zh-CN", "en"]
    draft_content_hash: Sha256
    renderer_input_identity: Sha256
    privacy_state_hash: Sha256
    approval: ApprovalRecord

    @model_validator(mode="after")
    def approval_matches_declared_snapshot(self) -> FrozenE6ApprovalBindingV1:
        expected = {
            "asset_id": self.asset_id,
            "version_id": self.version_id,
            "route": self.route,
            "language": self.language,
        }
        if any(getattr(self.approval, field) != value for field, value in expected.items()):
            raise ValueError("E6 approval record does not match its declared E7 snapshot")
        return self


class RenderedIdentityV1(ContractModel):
    schema_version: Literal["e7-delivery/v1"] = "e7-delivery/v1"
    route_draft_id: UUID
    asset_id: UUID
    version_id: UUID
    asset_version_hash: Sha256
    lineage_version_id: UUID
    lineage_parent_version_id: UUID | None = None
    relation_projection_hash: Sha256
    route: str
    language: Literal["zh-CN", "en"]
    route_draft_hash: Sha256
    renderer_input_identity: Sha256
    privacy_state_hash: Sha256
    draft_state: DraftState


class RenderBundleV1(ContractModel):
    identity: RenderedIdentityV1
    operation: DeliveryOperation
    approval_id: UUID | None = None
    html: str
    markdown: str
    canonical_json: str


class ExportBundleResultV1(ContractModel):
    request_id: UUID
    route_draft_id: UUID
    operation: Literal[
        DeliveryOperation.PRIVATE_DOWNLOAD,
        DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
    ]
    state: ExportRequestState
    records: list[ExportRecord]
    failed_formats: list[ExportFormat] = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool


class DeletionRequestV1(ContractModel):
    request_id: UUID
    asset_id: UUID
    state: DeletionRequestState
    confirmation_token: NonEmptyText
    created_at: AwareDatetime
    expires_at: AwareDatetime
    confirmed_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    job_id: UUID | None = None


class DeletionItemV1(ContractModel):
    path: NonEmptyText
    state: DeletionItemState
    attempts: int = Field(ge=0)
    last_error_code: str | None = None


class DeletionOutcomeV1(ContractModel):
    request_id: UUID
    asset_id: UUID
    job_id: UUID | None = None
    state: str
    terminal_state: str
    retryable: bool
    deleted_file_count: int = Field(ge=0)
    deleted_draft_count: int = Field(ge=0)
    deleted_export_count: int = Field(ge=0)
    failed_paths: list[str] = Field(default_factory=list)
    safe_user_message: NonEmptyText
    external_copy_notice: NonEmptyText = (
        "Product-managed copies are covered; external or user-created copies cannot be recalled."
    )


class AuditEventV1(ContractModel):
    event_id: UUID
    event_type: NonEmptyText
    asset_id: UUID
    draft_id: UUID | None = None
    request_id: UUID | None = None
    state: NonEmptyText
    occurred_at: AwareDatetime
    details: dict[str, str | int | bool | None] = Field(default_factory=dict)
