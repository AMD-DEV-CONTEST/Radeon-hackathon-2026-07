"""M2 Critical Moment Map API routes."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.experience_asset.application.m2 import M2ContractError, M2CriticalMomentService
from app.experience_asset.domain.m2 import (
    M2ConfirmRequestV1,
    M2CreateRequestV1,
    M2EditRequestV1,
    M2WorkspaceV1,
)
from app.experience_asset.persistence import (
    AssetNotFoundError,
    SQLiteAssetRepository,
    StorageConflictError,
)
from app.experience_asset.workflow import M2ProductionGraph


def build_m2_router(
    repository: SQLiteAssetRepository,
    graph: M2ProductionGraph,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/m2", tags=["m2"])
    service = M2CriticalMomentService(repository)

    def translate(action):
        try:
            return action()
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except M2ContractError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/assets/{asset_id}", response_model=M2WorkspaceV1, status_code=201)
    async def create(asset_id: UUID, request: M2CreateRequestV1) -> M2WorkspaceV1:
        try:
            return await graph.run_new(
                asset_id=asset_id,
                expected_m1_version_id=request.expected_m1_version_id,
            )
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except M2ContractError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/assets/{asset_id}", response_model=M2WorkspaceV1)
    async def get(asset_id: UUID) -> M2WorkspaceV1:
        return translate(lambda: service.get(asset_id))

    @router.patch("/assets/{asset_id}", response_model=M2WorkspaceV1)
    async def edit(asset_id: UUID, request: M2EditRequestV1) -> M2WorkspaceV1:
        return translate(lambda: service.edit(asset_id, request))

    @router.post("/assets/{asset_id}/confirm", response_model=M2WorkspaceV1)
    async def confirm(asset_id: UUID, request: M2ConfirmRequestV1) -> M2WorkspaceV1:
        return translate(lambda: service.confirm(asset_id, request))

    return router
