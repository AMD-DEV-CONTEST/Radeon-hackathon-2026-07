"""M5 route readiness, privacy review, and approval API.

This is the seam that makes E6 reachable from the product surface. PR #31's
policy slice is pure and stays pure: this router owns the projection read, the
durable write, and the HTTP translation, so the policy still runs against one
in-memory input and cannot acquire a persistence dependency by accident.

Every handler recomputes the M5 input from the current canonical version before
it decides anything. Reading a stored matrix and trusting it would let a user
approve an export against a card they edited in another tab, which is exactly
the staleness the approval binding exists to catch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.experience_asset.application.m5 import (
    M5ContextProjectionV1,
    PrivacyActionV1,
    RouteReadinessMatrixV1,
)
from app.experience_asset.application.m5.context_loader import M5ContextLoader
from app.experience_asset.application.m5.contracts import PrivacyReviewV1
from app.experience_asset.delivery import E7DeliveryService
from app.experience_asset.delivery.repository import DeliveryNotFoundError
from app.experience_asset.domain.models import ApprovalRecord, ContractModel
from app.experience_asset.persistence import AssetNotFoundError, SQLiteAssetRepository
from app.experience_asset.persistence.m5_store import M5Store
from app.experience_asset.policy.m5 import M5PolicyError, route_matrix_hash
from app.experience_asset.workflow.m5_graph import M5ProductionGraph


class M5WorkspaceV1(ContractModel):
    """Everything the review surface needs for one exact binding."""

    asset_id: UUID
    version_id: UUID
    content_hash: str
    stale_reason: str | None = None
    matrix: RouteReadinessMatrixV1 | None = None
    # Exposed alongside the matrix so a client can tell "the same five answers"
    # from "re-evaluated and unchanged" without diffing the decision list.
    matrix_hash: str | None = None
    privacy_review: PrivacyReviewV1 | None = None
    evidence_statements: dict[str, str] = Field(default_factory=dict)


class ResolveFindingRequestV1(BaseModel):
    action: PrivacyActionV1


class ApproveRequestV1(BaseModel):
    route_draft_id: UUID
    user_action: Literal["APPROVE_SHAREABLE_EXPORT"]
    idempotency_key: str


def build_m5_router(
    repository: SQLiteAssetRepository,
    delivery_provider: Callable[[], E7DeliveryService],
    graph: M5ProductionGraph,
    store: M5Store | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/m5", tags=["m5"])
    m5_store = store or M5Store(repository.database_path)
    context_loader = M5ContextLoader(repository)

    def _context(asset_id: UUID) -> tuple[M5ContextProjectionV1, str]:
        try:
            loaded = context_loader.load(asset_id)
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return loaded.context, loaded.content_hash

    def _evidence_statements(context: M5ContextProjectionV1) -> dict[str, str]:
        allowed = context.evidence.referenced_statement_ids()
        return {
            str(statement.statement_id): statement.text
            for statement in context.statements
            if statement.statement_id in allowed
        }

    def _deny(exc: M5PolicyError) -> HTTPException:
        return HTTPException(409, detail={"code": exc.code, "message": str(exc)})

    @router.get("/assets/{asset_id}/workspace", response_model=M5WorkspaceV1)
    async def workspace(asset_id: UUID) -> M5WorkspaceV1:
        context, content_hash = _context(asset_id)
        stale = context.stale_reason()
        if stale is not None:
            # A not-ready card is a visible state, not an error: the user needs
            # to see why M5 is unavailable so they can go and finish M4.
            return M5WorkspaceV1(
                asset_id=context.asset_id,
                version_id=context.version_id,
                content_hash=content_hash,
                stale_reason=stale,
                evidence_statements=_evidence_statements(context),
            )
        review = m5_store.read_privacy_review(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )
        matrix = m5_store.read_route_matrix(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )
        return M5WorkspaceV1(
            asset_id=context.asset_id,
            version_id=context.version_id,
            content_hash=content_hash,
            matrix=matrix,
            matrix_hash=route_matrix_hash(matrix) if matrix is not None else None,
            privacy_review=review,
            evidence_statements=_evidence_statements(context),
        )

    @router.post("/assets/{asset_id}/evaluate", response_model=M5WorkspaceV1, status_code=201)
    async def evaluate(asset_id: UUID) -> M5WorkspaceV1:
        """Run privacy review and the five-route matrix, then persist both."""

        context, content_hash = _context(asset_id)
        stale = context.stale_reason()
        if stale is not None:
            raise HTTPException(409, detail={"code": stale, "message": stale})
        try:
            await graph.run_evaluate(asset_id)
        except M5PolicyError as exc:
            raise _deny(exc) from exc
        review = m5_store.read_privacy_review(
            asset_id=asset_id,
            version_id=context.version_id,
            content_hash=content_hash,
        )
        matrix = m5_store.read_route_matrix(
            asset_id=asset_id,
            version_id=context.version_id,
            content_hash=content_hash,
        )
        if review is None or matrix is None:
            raise HTTPException(503, "M5 graph completed without persisted outputs")
        return M5WorkspaceV1(
            asset_id=context.asset_id,
            version_id=context.version_id,
            content_hash=content_hash,
            matrix=matrix,
            matrix_hash=route_matrix_hash(matrix) if matrix is not None else None,
            privacy_review=review,
            evidence_statements=_evidence_statements(context),
        )

    @router.post(
        "/assets/{asset_id}/privacy/findings/{finding_id}/resolve",
        response_model=M5WorkspaceV1,
    )
    async def resolve_finding(
        asset_id: UUID, finding_id: UUID, body: ResolveFindingRequestV1
    ) -> M5WorkspaceV1:
        context, content_hash = _context(asset_id)
        review = m5_store.read_privacy_review(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )
        if review is None:
            raise HTTPException(404, "no privacy review for this exact card")
        try:
            state = await graph.run_resolve(asset_id, finding_id=finding_id, action=body.action)
        except M5PolicyError as exc:
            raise _deny(exc) from exc
        if "CANONICAL_CHANGE_REQUIRED" in state.finding_codes:
            raise HTTPException(
                409,
                detail={
                    "code": "CANONICAL_CHANGE_REQUIRED",
                    "message": (
                        f"{body.action.value} requires an explicit canonical content edit; "
                        "no privacy resolution was saved."
                    ),
                },
            )
        result_review = m5_store.read_privacy_review(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )
        matrix = m5_store.read_route_matrix(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )
        if result_review is None or matrix is None:
            raise HTTPException(503, "M5 graph completed without persisted resolution")
        return M5WorkspaceV1(
            asset_id=context.asset_id,
            version_id=context.version_id,
            content_hash=content_hash,
            matrix=matrix,
            matrix_hash=route_matrix_hash(matrix),
            privacy_review=result_review,
            evidence_statements=_evidence_statements(context),
        )

    @router.post("/assets/{asset_id}/approvals", status_code=201)
    async def approve(asset_id: UUID, body: ApproveRequestV1) -> ApprovalRecord:
        context, content_hash = _context(asset_id)
        review = m5_store.read_privacy_review(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )
        matrix = m5_store.read_route_matrix(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )
        if review is None or matrix is None:
            raise HTTPException(409, "evaluate the routes before requesting approval")
        try:
            stored_draft = delivery_provider().repository.get_draft(body.route_draft_id)
        except DeliveryNotFoundError as exc:
            # The policy must never validate a RouteDraft reconstructed by a
            # browser. Only the E7-owned stored envelope is authoritative.
            raise HTTPException(404, "stored route draft was not found") from exc
        if stored_draft.asset_id != asset_id:
            raise HTTPException(409, "route draft belongs to another asset")
        try:
            state = await graph.run_approve(
                asset_id,
                route_draft_id=body.route_draft_id,
                user_action=body.user_action,
                idempotency_key=body.idempotency_key,
            )
        except M5PolicyError as exc:
            raise _deny(exc) from exc
        if state.approval_id is None:
            raise HTTPException(
                409,
                detail={
                    "code": state.finding_codes[0] if state.finding_codes else "APPROVAL_DENIED",
                    "message": state.safe_message or "Approval was denied.",
                },
            )
        return m5_store.read_approval(UUID(state.approval_id)).approval

    @router.get("/assets/{asset_id}/approvals")
    async def list_approvals(asset_id: UUID):
        context, content_hash = _context(asset_id)
        return m5_store.list_approvals(
            asset_id=asset_id, version_id=context.version_id, content_hash=content_hash
        )

    return router
