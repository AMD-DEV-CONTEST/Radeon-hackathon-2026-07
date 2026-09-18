"""Runtime mode status and transition endpoints."""

from fastapi import APIRouter, HTTPException

from buildguard.runtime_mode import (
    RuntimeMode,
    RuntimeModeConflict,
    RuntimeModeManager,
    RuntimeModeState,
)


def create_runtime_router(manager: RuntimeModeManager) -> APIRouter:
    router = APIRouter(prefix="/runtime-mode", tags=["runtime"])

    @router.get("", response_model=RuntimeModeState)
    def status() -> RuntimeModeState:
        return manager.status()

    @router.post("/enter/{mode}", response_model=RuntimeModeState)
    def enter(mode: RuntimeMode) -> RuntimeModeState:
        try:
            return manager.enter(mode)
        except RuntimeModeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/leave", response_model=RuntimeModeState)
    def leave() -> RuntimeModeState:
        return manager.leave()

    return router
