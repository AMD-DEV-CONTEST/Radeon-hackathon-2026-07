from __future__ import annotations

from fastapi import APIRouter

from agent_factory.file_capabilities import file_processing_capabilities


def create_file_router() -> APIRouter:
    router = APIRouter(prefix="/api/files")

    @router.get("/capabilities")
    async def get_file_capabilities():
        return file_processing_capabilities().to_public_dict()

    return router
