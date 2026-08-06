"""M4 Insight and Boundary Map API — routes registered, handlers owned elsewhere.

Ticket 01 fixes the paths and response models here so that the OpenAPI document,
the frontend types and the four parallel Wave-1 branches all agree before any
handler exists. Ticket 02 fills in the map operations; ticket 03 fills in
acceptance and readiness.

Handlers are the only thing later tickets add to this file. Restructuring the
module would put two Wave-1 branches into conflict over a file the contract
freeze already fixed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.experience_asset.api.routes.not_implemented import (
    NOT_IMPLEMENTED_RESPONSES,
    not_implemented,
)
from app.experience_asset.application.m4 import M4ContractError, M4MapService
from app.experience_asset.application.readiness import (
    ReadinessRefusal,
    ReadinessService,
)
from app.experience_asset.domain.m4 import (
    M4AcceptRequestV1,
    M4CreateRequestV1,
    M4EditRequestV1,
    M4RegenerateRequestV1,
    M4RunStatusV1,
    M4WorkspaceV1,
)
from app.experience_asset.domain.relation import KnowledgeCardReadinessRecordV1
from app.experience_asset.persistence import (
    AssetNotFoundError,
    SQLiteAssetRepository,
    StorageConflictError,
)
from app.experience_asset.workflow.m4_graph import M4ProductionGraph, M4WorkflowRunError


def build_m4_router(
    repository: SQLiteAssetRepository, graph: M4ProductionGraph | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/m4", tags=["m4"])
    service = M4MapService(repository)
    readiness_service = ReadinessService(repository)

    def translate(action):
        try:
            return action()
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except M4ContractError as exc:
            raise HTTPException(422, str(exc)) from exc

    async def run(**kwargs) -> M4WorkspaceV1:
        if graph is None:
            raise not_implemented("02", "M4 map generation")
        try:
            return await graph.run_new(**kwargs)
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except M4WorkflowRunError as exc:
            raise HTTPException(
                422,
                {
                    "run_id": str(exc.run_id),
                    "status_url": f"/api/v1/m4/assets/{kwargs['asset_id']}/runs/{exc.run_id}",
                    "message": str(exc),
                },
            ) from exc
        except M4ContractError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post(
        "/assets/{asset_id}",
        response_model=M4WorkspaceV1,
        status_code=201,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def create(asset_id: UUID, request: M4CreateRequestV1) -> M4WorkspaceV1:
        """Generate an Insight and Boundary Map from the accepted M3 ledger."""
        return await run(
            asset_id=asset_id,
            m3_id=request.expected_m3_artifact_id,
            version_id=request.expected_canonical_version_id,
        )

    @router.post(
        "/assets/{asset_id}/regenerate",
        response_model=M4WorkspaceV1,
        status_code=201,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def regenerate(
        asset_id: UUID, request: M4RegenerateRequestV1
    ) -> M4WorkspaceV1:
        """Rebuild a map invalidated by an upstream correction."""
        return await run(
            asset_id=asset_id,
            m3_id=request.expected_m3_artifact_id,
            version_id=request.expected_canonical_version_id,
            expected_invalidated_artifact_id=request.expected_invalidated_artifact_id,
        )

    @router.get(
        "/assets/{asset_id}",
        response_model=M4WorkspaceV1,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def read(asset_id: UUID) -> M4WorkspaceV1:
        """Read the current map together with the evidence behind each insight."""
        return translate(lambda: service.get(asset_id))

    @router.patch(
        "/assets/{asset_id}",
        response_model=M4WorkspaceV1,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def edit(asset_id: UUID, request: M4EditRequestV1) -> M4WorkspaceV1:
        """Edit map statements, producing a new canonical version."""
        return translate(lambda: service.edit(asset_id, request))

    @router.get(
        "/assets/{asset_id}/runs/{run_id}",
        response_model=M4RunStatusV1,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def run_status(asset_id: UUID, run_id: UUID) -> M4RunStatusV1:
        """Read progress or the terminal failure of one M4 run."""
        return translate(lambda: service.run_status(asset_id, run_id))

    @router.post(
        "/assets/{asset_id}/accept",
        response_model=KnowledgeCardReadinessRecordV1,
        status_code=201,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def accept(
        asset_id: UUID, request: M4AcceptRequestV1
    ) -> KnowledgeCardReadinessRecordV1:
        """Explicitly accept the map, minting version- and hash-bound readiness.

        Acceptance mints readiness and nothing else. It deliberately does not
        start discovery: running a search here would spend local model time and
        put historical summaries in front of someone who has not asked to
        compare anything, and it would make GRAG-02 unprovable because no test
        could then show that acceptance alone creates no run.
        """
        try:
            return readiness_service.accept(asset_id, request)
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ReadinessRefusal as exc:
            # The reason travels as a stable code beside the message: the two
            # states a user must tell apart — "finish your card" and "your card
            # changed underneath you" — have opposite next actions, and a single
            # generic 422 makes them indistinguishable in the UI.
            raise HTTPException(
                409 if exc.reason in {"ALREADY_ACCEPTED", "STORAGE_CONFLICT"} else 422,
                {"reason": exc.reason, "message": str(exc)},
            ) from exc

    @router.get(
        "/assets/{asset_id}/readiness",
        response_model=KnowledgeCardReadinessRecordV1,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def readiness(asset_id: UUID) -> KnowledgeCardReadinessRecordV1:
        """Read the active readiness record and its exact bindings."""
        record = readiness_service.read(asset_id)
        if record is None:
            # 404 rather than an empty body: "not ready" is a state the caller
            # has to branch on, and a 200 carrying nothing invites treating an
            # absent record as an unremarkable empty result.
            raise HTTPException(404, "this card has no active readiness record")
        return record

    return router
