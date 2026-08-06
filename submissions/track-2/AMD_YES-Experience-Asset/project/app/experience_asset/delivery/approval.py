"""Frozen E6 approval-service seam consumed by isolated E7 delivery."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.experience_asset.application.m5.context_loader import M5ContextLoader
from app.experience_asset.application.m5.service import M5IsolatedService
from app.experience_asset.domain.enums import ApprovalScope, PrivacyResolution
from app.experience_asset.domain.models import ApprovalRecord
from app.experience_asset.persistence.m5_store import M5Store, M5StoreError
from app.experience_asset.policy.m5 import route_matrix_hash

from .models import FrozenE6ApprovalBindingV1, StoredRouteDraftV1


class ApprovalRejectedError(PermissionError):
    """The supplied approval is missing, stale, or bound to another delivery."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ApprovalValidator(Protocol):
    """The live E6 service will implement this exact validation boundary."""

    def validate_external_export(
        self,
        draft: StoredRouteDraftV1,
        approval: ApprovalRecord | None,
    ) -> ApprovalRecord: ...


class FrozenE6ApprovalAdapter:
    """Consume immutable E6-issued fixtures without reimplementing E6 hash policy."""

    def __init__(
        self,
        bindings: tuple[FrozenE6ApprovalBindingV1, ...] = (),
    ) -> None:
        self._bindings: dict[UUID, FrozenE6ApprovalBindingV1] = {}
        for binding in bindings:
            self.register_fixture(binding)

    def register_fixture(self, binding: FrozenE6ApprovalBindingV1) -> None:
        existing = self._bindings.get(binding.route_draft_id)
        if existing is not None and existing != binding:
            raise ValueError("route draft already has another frozen E6 approval binding")
        self._bindings[binding.route_draft_id] = binding

    def validate_external_export(
        self,
        draft: StoredRouteDraftV1,
        approval: ApprovalRecord | None,
    ) -> ApprovalRecord:
        if approval is None:
            raise ApprovalRejectedError(
                "APPROVAL_MISSING",
                "An exact-bound ApprovalRecord is required for an external-audience export.",
            )
        binding = self._bindings.get(draft.draft.route_draft_id)
        if binding is None:
            raise ApprovalRejectedError(
                "APPROVAL_BINDING_UNAVAILABLE",
                "No E6-issued approval binding fixture exists for this exact RouteDraft.",
            )
        draft_snapshot = {
            "route_draft_id": draft.draft.route_draft_id,
            "asset_id": draft.asset_id,
            "version_id": draft.draft.canonical_version_id,
            "asset_version_hash": draft.asset_version_hash,
            "relation_projection_hash": draft.relation_projection_hash,
            "route": draft.draft.route,
            "language": draft.draft.language,
            "draft_content_hash": draft.draft.content_hash,
            "renderer_input_identity": draft.renderer_input_identity,
            "privacy_state_hash": draft.privacy_state_hash,
        }
        for field, actual_value in draft_snapshot.items():
            if getattr(binding, field) != actual_value:
                raise ApprovalRejectedError(
                    "APPROVAL_BINDING_MISMATCH",
                    f"Saved RouteDraft {field} does not match the E6-issued binding.",
                )
        if approval != binding.approval:
            raise ApprovalRejectedError(
                "APPROVAL_BINDING_MISMATCH",
                "ApprovalRecord does not exactly match the E6-issued binding fixture.",
            )
        if approval.scope is not ApprovalScope.SHAREABLE_EXPORT:
            raise ApprovalRejectedError(
                "APPROVAL_SCOPE_INVALID",
                "ApprovalRecord scope is not SHAREABLE_EXPORT.",
            )
        if approval.user_action != "APPROVE_SHAREABLE_EXPORT":
            raise ApprovalRejectedError(
                "APPROVAL_ACTION_INVALID",
                "ApprovalRecord does not contain the explicit E6 external-share action.",
            )
        if approval.finding_resolutions != draft.privacy_finding_resolutions:
            raise ApprovalRejectedError(
                "APPROVAL_PRIVACY_BINDING_MISMATCH",
                "E6 finding resolutions do not match the saved E7 privacy snapshot.",
            )
        if any(
            resolution is PrivacyResolution.OPEN
            for resolution in draft.privacy_finding_resolutions.values()
        ):
            raise ApprovalRejectedError(
                "PRIVACY_FINDINGS_OPEN",
                "All findings must be resolved or acknowledged before external export.",
            )
        if approval.approved_at < draft.created_at:
            raise ApprovalRejectedError(
                "APPROVAL_STALE",
                "ApprovalRecord predates the exact saved RouteDraft.",
            )
        return approval


class PersistedM5ApprovalAdapter:
    """Validate external export against live persisted M5 and E7 truth."""

    def __init__(self, context_loader: M5ContextLoader, store: M5Store) -> None:
        self._context_loader = context_loader
        self._store = store
        self._service = M5IsolatedService()

    def validate_external_export(
        self,
        draft: StoredRouteDraftV1,
        approval: ApprovalRecord | None,
    ) -> ApprovalRecord:
        if approval is None:
            raise ApprovalRejectedError(
                "APPROVAL_MISSING",
                "An exact persisted approval is required for external export.",
            )
        try:
            stored = self._store.read_approval(approval.approval_id)
        except M5StoreError as exc:
            raise ApprovalRejectedError(
                "APPROVAL_NOT_FOUND",
                "The supplied approval is not present in local M5 storage.",
            ) from exc
        if stored.approval != approval:
            raise ApprovalRejectedError(
                "APPROVAL_BINDING_MISMATCH",
                "The supplied approval differs from the persisted approval record.",
            )
        if stored.draft_id is None:
            raise ApprovalRejectedError(
                "APPROVAL_BINDING_UNAVAILABLE",
                "This legacy approval predates exact RouteDraft identity binding; "
                "approve the current draft again.",
            )
        if stored.stale_since is not None:
            raise ApprovalRejectedError(
                "APPROVAL_STALE",
                stored.stale_reason or "The persisted approval is stale.",
            )
        if (
            stored.draft_id != draft.draft.route_draft_id
            or stored.draft_binding_hash != draft.renderer_input_identity
            or stored.asset_id != draft.asset_id
            or stored.version_id != draft.draft.canonical_version_id
        ):
            raise ApprovalRejectedError(
                "APPROVAL_BINDING_MISMATCH",
                "The approval is bound to another persisted RouteDraft snapshot.",
            )

        loaded = self._context_loader.load(draft.asset_id)
        context = loaded.context
        if (
            loaded.content_hash != stored.content_hash
            or context.version_id != draft.draft.canonical_version_id
        ):
            raise ApprovalRejectedError(
                "APPROVAL_STALE",
                "The canonical asset changed after approval.",
            )
        review = self._store.read_privacy_review(
            asset_id=draft.asset_id,
            version_id=context.version_id,
            content_hash=loaded.content_hash,
        )
        matrix = self._store.read_route_matrix(
            asset_id=draft.asset_id,
            version_id=context.version_id,
            content_hash=loaded.content_hash,
        )
        if review is None or matrix is None:
            raise ApprovalRejectedError(
                "APPROVAL_CONTEXT_MISSING",
                "The bound privacy review or route matrix is no longer current.",
            )
        if route_matrix_hash(matrix) != stored.matrix_hash:
            raise ApprovalRejectedError(
                "APPROVAL_STALE",
                "The route matrix changed after approval.",
            )
        validity = self._service.approval_status(
            approval,
            context,
            matrix,
            review,
            draft=draft.draft,
            renderer_input_hash=draft.renderer_input_identity,
        )
        if not validity.valid:
            raise ApprovalRejectedError(
                validity.reason_codes[0],
                "; ".join(validity.reason_codes),
            )
        return approval
