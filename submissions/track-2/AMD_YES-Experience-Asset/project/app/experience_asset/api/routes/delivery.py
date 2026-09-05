"""E7 delivery API — preview, export, and confirmed deletion.

PR #34 delivered E7 as a service with its own repository and no HTTP surface,
so preview, export and deletion were reachable only from Python. The Baseline
has to be exercisable through the actual product, and a demo that ends at a
test file is not a demo.

Preview is deliberately separate from export: reading your own draft in your own
app is not an external share, and requiring approval for it would train the user
to approve before they have seen what they are approving.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.experience_asset.application.m5.context_loader import M5ContextLoader
from app.experience_asset.delivery import (
    ApprovalRejectedError,
    DeliveryOperation,
    E7DeliveryService,
)
from app.experience_asset.delivery.models import RouteDraftContentV1
from app.experience_asset.delivery.repository import (
    DeliveryConflictError,
    DeliveryNotFoundError,
    DeliveryPersistenceError,
)
from app.experience_asset.delivery.service import (
    RouteDraftContractError,
    SecondConfirmationRequiredError,
    canonical_asset_hash,
)
from app.experience_asset.domain.enums import RouteType
from app.experience_asset.persistence import AssetNotFoundError
from app.experience_asset.persistence.m5_store import M5Store, M5StoreError


class ExportRequestV1(BaseModel):
    operation: DeliveryOperation = DeliveryOperation.PRIVATE_DOWNLOAD
    approval_id: UUID | None = None


class CreateRouteDraftRequestV1(BaseModel):
    create_request_id: UUID
    route: RouteType
    language: str
    content: RouteDraftContentV1


class DeletionRequestBodyV1(BaseModel):
    asset_id: UUID


class ConfirmDeletionRequestV1(BaseModel):
    confirmation_token: str
    second_confirmation: bool = False


def build_delivery_router(
    provider: Callable[[], E7DeliveryService],
    context_loader: M5ContextLoader,
    m5_store: M5Store,
) -> APIRouter:
    """Take a provider, not a service: the artifact store is built at startup."""

    router = APIRouter(prefix="/api/v1/delivery", tags=["delivery"])

    def delivery() -> E7DeliveryService:
        return provider()

    def translate(action):
        try:
            return action()
        except DeliveryNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except M5StoreError as exc:
            raise HTTPException(404, str(exc)) from exc
        except SecondConfirmationRequiredError as exc:
            # 428: the request is well formed but the user has not taken the
            # second, explicit step an irreversible action requires.
            raise HTTPException(428, str(exc)) from exc
        except ApprovalRejectedError as exc:
            raise HTTPException(403, detail={"code": exc.code, "message": str(exc)}) from exc
        except DeliveryConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RouteDraftContractError as exc:
            raise HTTPException(422, str(exc)) from exc
        except DeliveryPersistenceError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/assets/{asset_id}/drafts", status_code=201)
    async def create_draft(asset_id: UUID, body: CreateRouteDraftRequestV1):
        def save():
            loaded = context_loader.load(asset_id)
            stale = loaded.context.stale_reason()
            if stale is not None:
                raise DeliveryConflictError(stale)
            review = m5_store.read_privacy_review(
                asset_id=asset_id,
                version_id=loaded.context.version_id,
                content_hash=loaded.content_hash,
            )
            matrix = m5_store.read_route_matrix(
                asset_id=asset_id,
                version_id=loaded.context.version_id,
                content_hash=loaded.content_hash,
            )
            if review is None or matrix is None:
                raise DeliveryConflictError("evaluate M5 before saving a route draft")
            evaluation_run_id = m5_store.read_route_matrix_run_id(
                asset_id=asset_id,
                version_id=loaded.context.version_id,
                content_hash=loaded.content_hash,
            )
            if evaluation_run_id is None:
                raise DeliveryConflictError("M5 evaluation provenance is unavailable")
            expected_labels = (
                {
                    "title": "我的可复用经验",
                    "heading": "核心经验",
                    "notice": "对外分享前请复核内容和隐私状态。",
                }
                if body.language == "zh-CN"
                else {
                    "title": "My reusable experience",
                    "heading": "Core evidence",
                    "notice": "Review content and privacy state before external sharing.",
                }
            )
            if (
                body.content.title != expected_labels["title"]
                or any(
                    section.heading != expected_labels["heading"]
                    for section in body.content.sections
                )
                or body.content.notices != [expected_labels["notice"]]
            ):
                raise RouteDraftContractError(
                    "live route draft labels and notices are server-defined neutral text"
                )
            current_text = {
                statement.statement_id: " ".join(statement.text.split())
                for statement in loaded.context.statements
            }
            for claim in body.content.all_claims():
                referenced_text = {
                    current_text.get(statement_id) for statement_id in claim.statement_ids
                }
                if " ".join(claim.text.split()) not in referenced_text:
                    raise RouteDraftContractError(
                        "live route draft claims must be selected from exact canonical evidence"
                    )
            return delivery().save_route_draft(
                create_request_id=body.create_request_id,
                asset=loaded.asset,
                asset_version_hash=canonical_asset_hash(loaded.asset),
                relation_projection_hash=matrix.relation_projection_hash,
                route=body.route,
                language=body.language,
                content=body.content,
                created_by_run_id=evaluation_run_id,
                route_decisions=matrix.decisions,
                privacy_findings=review.findings,
            )

        return translate(save)

    @router.get("/drafts/{draft_id}/preview")
    async def preview(draft_id: UUID):
        bundle = translate(lambda: delivery().preview(draft_id))
        return {
            "identity": bundle.identity.model_dump(mode="json"),
            "operation": bundle.operation.value,
            "html": bundle.html,
            "markdown": bundle.markdown,
            "json": bundle.canonical_json,
        }

    @router.post("/drafts/{draft_id}/exports", status_code=201)
    async def export_bundle(draft_id: UUID, body: ExportRequestV1):
        approval = None
        if body.approval_id is not None:
            approval = translate(lambda: m5_store.read_approval(body.approval_id)).approval
        result = translate(
            lambda: delivery().export_bundle(
                request_id=uuid4(),
                draft_id=draft_id,
                operation=body.operation,
                approval=approval,
            )
        )
        return result

    @router.post("/deletion-requests", status_code=201)
    async def request_deletion(body: DeletionRequestBodyV1):
        return translate(
            lambda: delivery().request_deletion(request_id=uuid4(), asset_id=body.asset_id)
        )

    @router.post("/deletion-requests/{request_id}/confirm")
    async def confirm_deletion(request_id: UUID, body: ConfirmDeletionRequestV1):
        return translate(
            lambda: delivery().confirm_deletion(
                request_id=request_id,
                confirmation_token=body.confirmation_token,
                second_confirmation=body.second_confirmation,
            )
        )

    return router
