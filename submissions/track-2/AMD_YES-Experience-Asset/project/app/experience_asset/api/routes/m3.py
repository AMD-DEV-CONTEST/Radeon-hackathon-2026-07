"""M3 Decision and Evidence Ledger API."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.experience_asset.application.m3 import M3ContractError, M3LedgerService
from app.experience_asset.domain.m3 import (
    M3ConfirmRequestV1,
    M3CreateRequestV1,
    M3EditRequestV1,
    M3RegenerateRequestV1,
    M3RunStatusV1,
    M3WorkspaceV1,
    public_m3_failure_code,
)
from app.experience_asset.persistence import (
    AssetNotFoundError,
    SQLiteAssetRepository,
    StorageConflictError,
)
from app.experience_asset.workflow.m3_graph import M3ProductionGraph, M3WorkflowRunError


def build_m3_router(repository: SQLiteAssetRepository, graph: M3ProductionGraph) -> APIRouter:
    router = APIRouter(prefix="/api/v1/m3", tags=["m3"])
    service = M3LedgerService(repository)

    def translate(action):
        try:
            return action()
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except M3ContractError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/assets/{asset_id}", response_model=M3WorkspaceV1, status_code=201)
    async def create(asset_id: UUID, request: M3CreateRequestV1):
        try:
            return await graph.run_new(
                asset_id=asset_id,
                m2_id=request.expected_m2_artifact_id,
                version_id=request.expected_canonical_version_id,
            )
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except M3WorkflowRunError as exc:
            raise HTTPException(
                422,
                {
                    "run_id": str(exc.run_id),
                    "status_url": f"/api/v1/m3/runs/{exc.run_id}",
                    "message": str(exc),
                },
            ) from exc
        except M3ContractError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/runs/{run_id}", response_model=M3RunStatusV1)
    async def run_status(run_id: UUID):
        terminal = repository.get_terminal_result(run_id)
        if terminal is None:
            raise HTTPException(404, "M3 run not found or still has no durable outcome")
        outcome = repository.get_m3_run_outcome(run_id) or {}
        codes = __import__("json").loads(str(outcome.get("finding_codes_json", "[]")))
        return {
            "run_id": str(run_id),
            "terminal_state": terminal.state.value,
            "code": (
                terminal.state.value
                if terminal.state.value == "SUCCEEDED"
                else public_m3_failure_code(terminal.state, codes)
            ),
            "model_calls_used": terminal.model_call_count,
            "structured_repairs_used": outcome.get("structured_repair_count", 0),
            "replans_used": outcome.get("replan_count", 0),
            "finding_codes": codes,
            "safe_user_message": terminal.safe_user_message,
            "recovery_action": terminal.recovery_action,
        }

    @router.get("/assets/{asset_id}", response_model=M3WorkspaceV1)
    async def get(asset_id: UUID):
        return translate(lambda: service.get(asset_id))

    @router.patch("/assets/{asset_id}", response_model=M3WorkspaceV1)
    async def edit(asset_id: UUID, request: M3EditRequestV1):
        return translate(lambda: service.edit(asset_id, request))

    @router.post("/assets/{asset_id}/confirm", response_model=M3WorkspaceV1)
    async def confirm(asset_id: UUID, request: M3ConfirmRequestV1):
        return translate(lambda: service.confirm(asset_id, request))

    @router.post("/assets/{asset_id}/regenerate", response_model=M3WorkspaceV1)
    async def regenerate(asset_id: UUID, request: M3RegenerateRequestV1):
        try:
            return await graph.run_new(
                asset_id=asset_id,
                m2_id=request.expected_m2_artifact_id,
                version_id=request.expected_canonical_version_id,
                expected_invalidated_artifact_id=request.expected_invalidated_artifact_id,
            )
        except AssetNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except StorageConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except M3WorkflowRunError as exc:
            raise HTTPException(
                422,
                {
                    "run_id": str(exc.run_id),
                    "status_url": f"/api/v1/m3/runs/{exc.run_id}",
                    "message": str(exc),
                },
            ) from exc
        except M3ContractError as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
