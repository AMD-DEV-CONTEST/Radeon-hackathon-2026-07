"""
ILS v2.3 — Task Decomposer API Router
Mounted at /decomposer/* in the orchestrator.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from iron_law.decomposer import (
    decompose,
    get_pattern,
    list_patterns,
    record_decomposition_outcome,
    store_pattern,
    embed_text,
)

logger = logging.getLogger("iron_law.decomposer_router")

router = APIRouter(prefix="/decomposer", tags=["decomposer"])


# -- Request/Response models -----------------------------------------------

class DecomposeRequest(BaseModel):
    """Task decomposition request."""
    goal: str = Field(..., min_length=5, max_length=5000, description="Natural language goal to decompose")
    project: str = Field(default="default", max_length=64)
    task_id: str | None = Field(default=None, description="Optional task ID for embedding cache")
    force_fresh: bool = Field(default=False, description="Skip pattern matching, always generate fresh")


class DecomposeResponse(BaseModel):
    """Task decomposition response."""
    decomposition: list[dict[str, Any]]
    source: str
    matched_pattern_id: str | None = None
    similarity: float | None = None
    intent_pattern: str
    embedding_stored: bool
    task_count: int


class OutcomeRequest(BaseModel):
    """Record outcome of a decomposition pattern."""
    pattern_id: str
    success: bool


class StorePatternRequest(BaseModel):
    """Manually store a decomposition pattern."""
    intent_pattern: str = Field(..., min_length=3, max_length=200)
    dag: list[dict[str, Any]] = Field(..., min_length=1)
    project: str = Field(default="default", max_length=64)


# -- Endpoints --------------------------------------------------------------

@router.post("/decompose", response_model=DecomposeResponse)
async def api_decompose(req: DecomposeRequest) -> DecomposeResponse:
    """
    Decompose a natural language goal into a task DAG.

    Uses vector similarity to find matching decomposition patterns.
    If a high-confidence match is found, adapts the cached pattern.
    Otherwise, generates a fresh decomposition via LLM.
    """
    try:
        result = decompose(
            goal=req.goal,
            project=req.project,
            task_id=req.task_id,
            force_fresh=req.force_fresh,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Decomposition failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Decomposition failed: " + str(exc),
        )

    return DecomposeResponse(
        decomposition=result["decomposition"],
        source=result["source"],
        matched_pattern_id=result["matched_pattern_id"],
        similarity=result["similarity"],
        intent_pattern=result["intent_pattern"],
        embedding_stored=result["embedding_stored"],
        task_count=len(result["decomposition"]),
    )


@router.post("/outcome", status_code=status.HTTP_204_NO_CONTENT)
async def api_record_outcome(req: OutcomeRequest) -> None:
    """Record the outcome (success/failure) of a decomposition pattern."""
    record_decomposition_outcome(req.pattern_id, req.success)


@router.post("/patterns", status_code=status.HTTP_201_CREATED)
async def api_store_pattern(req: StorePatternRequest) -> dict[str, Any]:
    """Manually store a decomposition pattern with auto-computed embedding."""
    try:
        embedding = embed_text(req.intent_pattern)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service unavailable: " + str(exc),
        )

    pattern_id = store_pattern(
        intent_pattern=req.intent_pattern,
        dag=req.dag,
        embedding=embedding,
        project=req.project,
    )
    return {"pattern_id": pattern_id, "status": "stored"}


@router.get("/patterns")
async def api_list_patterns(
    project: str = Query(default="default", max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List decomposition patterns for a project."""
    patterns = list_patterns(project=project, limit=limit)
    return {"project": project, "count": len(patterns), "patterns": patterns}


@router.get("/patterns/{pattern_id}")
async def api_get_pattern(pattern_id: str) -> dict[str, Any]:
    """Get a specific decomposition pattern by ID."""
    pattern = get_pattern(pattern_id)
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pattern not found: " + pattern_id,
        )
    return pattern


@router.get("/health")
async def health() -> dict[str, Any]:
    """Decomposer health check."""
    embedding_ok = False
    try:
        embed_text("health check")
        embedding_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "service": "decomposer",
        "embedding_service": "ok" if embedding_ok else "unavailable",
    }
