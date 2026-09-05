"""M1 Experience Brief API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.experience_asset.application.m1 import M1ExperienceBriefService
from app.experience_asset.application.m1.service import M1ContractError
from app.experience_asset.domain.enums import AssetLifecycle
from app.experience_asset.domain.m1 import (
    M1AgentRunRequestV1,
    M1BriefEditRequestV1,
    M1ConfirmRequestV1,
    M1IngestRequestV1,
    M1QuestionActionV1,
    M1VersionActionRequestV1,
    M1WorkspaceV1,
)
from app.experience_asset.persistence import (
    AssetNotFoundError,
    SQLiteAssetRepository,
    StorageConflictError,
)
from app.experience_asset.workflow import M1ProductionGraph


def build_m1_router(
    repository: SQLiteAssetRepository,
    agent_graph: M1ProductionGraph,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/m1", tags=["m1"])
    service = M1ExperienceBriefService(repository)

    @router.post("/assets", response_model=M1WorkspaceV1, status_code=201)
    async def ingest(request: M1IngestRequestV1) -> M1WorkspaceV1:
        return service.ingest(request)

    @router.get("/assets/{asset_id}", response_model=M1WorkspaceV1)
    async def get_workspace(asset_id: UUID) -> M1WorkspaceV1:
        try:
            return service.get(asset_id)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.patch("/assets/{asset_id}/brief", response_model=M1WorkspaceV1)
    async def edit_brief(
        asset_id: UUID,
        request: M1BriefEditRequestV1,
    ) -> M1WorkspaceV1:
        try:
            return service.edit(asset_id, request)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except M1ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/assets/{asset_id}/questions/{question_id}",
        response_model=M1WorkspaceV1,
    )
    async def act_on_question(
        asset_id: UUID,
        question_id: UUID,
        request: M1QuestionActionV1,
    ) -> M1WorkspaceV1:
        try:
            return service.act_on_question(asset_id, question_id, request)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except M1ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/assets/{asset_id}/pause", response_model=M1WorkspaceV1)
    async def pause(
        asset_id: UUID,
        request: M1VersionActionRequestV1,
    ) -> M1WorkspaceV1:
        try:
            return service.pause(asset_id, request)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except M1ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/assets/{asset_id}/resume", response_model=M1WorkspaceV1)
    async def resume(
        asset_id: UUID,
        request: M1VersionActionRequestV1,
    ) -> M1WorkspaceV1:
        try:
            return service.resume(asset_id, request)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except M1ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/assets/{asset_id}/confirm", response_model=M1WorkspaceV1)
    async def confirm(
        asset_id: UUID,
        request: M1ConfirmRequestV1,
    ) -> M1WorkspaceV1:
        try:
            return service.confirm(asset_id, request)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except M1ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/assets/{asset_id}/agent-runs", response_model=M1WorkspaceV1)
    async def run_current_source_agent(
        asset_id: UUID,
        request: M1AgentRunRequestV1,
    ) -> M1WorkspaceV1:
        try:
            current = repository.get_current(asset_id)
            if current.version_id != request.expected_version_id:
                raise StorageConflictError(
                    "current version changed; reload before running Agent"
                )
            if current.lifecycle is AssetLifecycle.PAUSED:
                raise M1ContractError("resume the asset before running Agent")
            await agent_graph.run_new(
                asset_id=current.asset_id,
                expected_version_id=current.version_id,
                user_goal=request.user_goal,
                allow_current_source_search=request.allow_current_source_search,
            )
            return service.get(asset_id)
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except M1ContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
