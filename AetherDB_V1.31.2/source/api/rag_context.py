"""Compatibility endpoint for the scoped ContextMap pipeline."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import get_current_user_role
from app.models import ContextMapRequest, ContextNeed
from services.context_engine import create_context_map, owner_fingerprint

router = APIRouter(tags=["rag_context"])


@router.post("/api/rag/context")
def upgraded_rag_context(
    payload: ContextMapRequest,
    request: Request,
    role: str = Depends(get_current_user_role),
):
    """Return scoped lightweight candidates; raw evidence requires later approval."""
    try:
        result = create_context_map(payload, owner_fingerprint(request.headers.get("x-api-key", "")))
    except ValueError:
        raise HTTPException(400, "Invalid context scope or request")
    except Exception:
        raise HTTPException(500, "Context map failed")
    return {
        "task_id": result["task_id"],
        "candidates": result["candidates"],
        "token_estimate": sum(item["estimated_tokens"] for item in result["candidates"]),
        "context": "",
        "approval_required": True,
    }
