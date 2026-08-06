"""Scoped ContextMap API."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import get_current_user_role
from app.models import ContextApprovalRequest, ContextMapRequest, EvidencePackRequest
from services.context_engine import (
    ContextTaskExpired,
    approve_context,
    build_evidence_pack,
    create_context_map,
    get_context_candidates,
    list_context_tasks,
    migrate_context_owner,
    owner_fingerprint,
    owner_principal,
)

router = APIRouter(tags=["context"])


def _owner(database_id: str, request: Request, role: str) -> str:
    principal = owner_principal(role)
    migrate_context_owner(
        database_id,
        owner_fingerprint(request.headers.get("x-api-key", "")),
        principal,
    )
    return principal


@router.post("/api/context/map")
def api_create_context_map(
    payload: ContextMapRequest,
    request: Request,
    role: str = Depends(get_current_user_role),
):
    try:
        return create_context_map(payload, _owner(payload.database_id, request, role))
    except ValueError:
        raise HTTPException(400, "Invalid context scope or request")
    except Exception:
        raise HTTPException(500, "Context map failed")


@router.get("/api/context/tasks")
def api_list_context_tasks(
    database_id: str,
    request: Request,
    status: str | None = None,
    include_expired: bool = False,
    limit: int = 100,
    role: str = Depends(get_current_user_role),
):
    try:
        return {
            "tasks": list_context_tasks(
                database_id,
                _owner(database_id, request, role),
                status=status,
                include_expired=include_expired,
                limit=limit,
            )
        }
    except ValueError:
        raise HTTPException(404, "Database not found")


@router.get("/api/context/tasks/{task_id}/candidates")
def api_get_context_candidates(
    task_id: str,
    database_id: str,
    request: Request,
    role: str = Depends(get_current_user_role),
):
    try:
        return get_context_candidates(database_id, task_id, _owner(database_id, request, role))
    except ContextTaskExpired:
        raise HTTPException(410, "Context task expired")
    except KeyError:
        raise HTTPException(404, "Context task not found")
    except Exception:
        raise HTTPException(400, "Invalid context request")


@router.post("/api/context/tasks/{task_id}/approval")
def api_approve_context(
    task_id: str,
    database_id: str,
    payload: ContextApprovalRequest,
    request: Request,
    role: str = Depends(get_current_user_role),
):
    try:
        return approve_context(
            database_id,
            task_id,
            payload.items,
            _owner(database_id, request, role),
        )
    except ContextTaskExpired:
        raise HTTPException(410, "Context task expired")
    except KeyError:
        raise HTTPException(404, "Context task not found")
    except ValueError:
        raise HTTPException(400, "Candidate does not belong to context task")
    except Exception:
        raise HTTPException(500, "Context approval failed")


@router.post("/api/context/tasks/{task_id}/evidence-pack")
def api_build_evidence_pack(
    task_id: str,
    database_id: str,
    payload: EvidencePackRequest,
    request: Request,
    role: str = Depends(get_current_user_role),
):
    try:
        return build_evidence_pack(
            database_id,
            task_id,
            _owner(database_id, request, role),
            payload.budget,
            payload.media_budget,
        )
    except ContextTaskExpired:
        raise HTTPException(410, "Context task expired")
    except KeyError:
        raise HTTPException(404, "Context task not found")
    except ValueError:
        raise HTTPException(409, "Context evidence snapshot is invalid")
    except Exception:
        raise HTTPException(500, "Evidence pack failed")
