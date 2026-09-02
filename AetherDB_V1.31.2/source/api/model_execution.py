"""Authenticated NDJSON model execution endpoint."""

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, replace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.dependencies.auth import require_capability
from app.deployment import Capability, EffectivePrincipal
from app.models import ModelExecuteRequest, ModelRecoveryConfirmRequest
from services.database_registry import get_database, get_db_path
from services.model_execution import ModelTaskRequest, get_default_gateway
from services.model_streaming import stream_model_task
from services.ollama_execution import (
    cancel_task_executions,
    list_task_executions,
)
from services.context_engine import build_evidence_messages, build_evidence_pack, owner_fingerprint
from services.context_engine import migrate_context_owner, owner_principal
from services.model_data_boundary import (
    ModelDataBoundaryError,
    claim_data_manifest,
    confirm_data_manifest,
    create_data_manifest,
    enforce_model_data_policy,
    estimate_payload_size,
    get_data_manifest,
    is_cloud_provider,
    validate_selected_assets,
)
from services.model_recovery import (
    ModelRecoveryError,
    claim_recovery_execution,
    confirm_recovery_ticket,
    prepare_recovery_execution,
    safe_model_candidate,
    safe_model_candidates,
)
from services.model_registry import get_model_profile, get_provider
from services.model_routing import RouteStatus

router = APIRouter(tags=["model_execution"])
require_model_execution = require_capability(Capability.EXECUTE_CREATION_ASSISTANCE)


def get_execution_gateway():
    return get_default_gateway()


@dataclass(frozen=True)
class PreparedExecution:
    model_request: ModelTaskRequest
    original_messages: tuple[dict, ...]
    approved_context_ids: tuple[str, ...]
    selected_asset_ids: tuple[str, ...]


def _validate_scope(database_id: str, book_id: str | None, chapter_id: str | None):
    if not get_database(database_id):
        raise HTTPException(404, "Database not found")
    if chapter_id and not book_id:
        raise HTTPException(400, "chapter_id requires book_id")
    if not book_id:
        return
    with sqlite3.connect(get_db_path(database_id)) as conn:
        if not conn.execute("SELECT 1 FROM books WHERE book_id=?", (book_id,)).fetchone():
            raise HTTPException(404, "Book not found in database")
        if chapter_id and not conn.execute(
            "SELECT 1 FROM chapters WHERE chapter_id=? AND book_id=? AND is_active=1",
            (chapter_id, book_id),
        ).fetchone():
            raise HTTPException(404, "Chapter not found in book")


async def encode_events(event_source):
    async for event in event_source:
        yield json.dumps(
            event.model_dump(),
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n"


def _recovery_http_error(exc: ModelRecoveryError):
    status = 404 if exc.code == "RECOVERY_TICKET_NOT_FOUND" else 409
    return HTTPException(status, detail={"code": exc.code, "message": str(exc)})


def _validate_task_id(task_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9:._-]{1,128}", task_id):
        raise HTTPException(400, "Invalid task id")
    return task_id


def _data_boundary_http_error(exc: ModelDataBoundaryError):
    return HTTPException(
        exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _route_http_error(route):
    return HTTPException(
        409,
        detail={
            "code": f"MODEL_ROUTE_{route.status.value.upper()}",
            "message": "A unique eligible model must be resolved before creating a data manifest.",
            "route_status": route.status.value,
            "candidates": safe_model_candidates(
                [candidate.model_profile_id for candidate in route.candidates]
            ),
        },
    )


def _prepare_execution(
    payload: ModelExecuteRequest,
    request: Request,
    principal: EffectivePrincipal,
) -> PreparedExecution:
    _validate_scope(payload.database_id, payload.book_id, payload.chapter_id)
    original_messages = tuple(message.model_dump() for message in payload.messages)
    messages = list(original_messages)
    approved_context_ids: list[str] = []
    evidence_asset_ids: list[str] = []
    if payload.context_task_id:
        if payload.evidence_budget is None:
            raise HTTPException(400, "evidence_budget is required with context_task_id")
        try:
            context_owner = owner_principal(principal.credential_role)
            migrate_context_owner(
                payload.database_id,
                owner_fingerprint(request.headers.get("x-api-key", "")),
                context_owner,
            )
            pack = build_evidence_pack(
                payload.database_id,
                payload.context_task_id,
                context_owner,
                payload.evidence_budget,
                payload.evidence_media_budget,
            )
        except KeyError:
            raise HTTPException(404, "Context task not found")
        except ValueError:
            raise HTTPException(409, "Context evidence snapshot is invalid")
        if payload.book_id != pack["book_id"]:
            raise HTTPException(409, "Context task is outside the requested book scope")
        approved_context_ids = [item["candidate_id"] for item in pack["items"]]
        evidence_asset_ids = [
            item["media_reference"]["asset_id"]
            for item in pack["items"]
            if item.get("media_reference")
            and item["media_reference"].get("asset_id")
        ]
        evidence_messages = build_evidence_messages(
            system_core="Follow the authenticated model task and output contract.",
            task=payload.task_type,
            current_text="",
            evidence_pack=pack,
            output_contract="json" if payload.requires_json else "text",
        )
        messages.extend(evidence_messages)
    try:
        selected_asset_ids = validate_selected_assets(
            payload.database_id,
            payload.book_id,
            (*payload.selected_asset_ids, *evidence_asset_ids),
        )
    except ModelDataBoundaryError as exc:
        raise _data_boundary_http_error(exc) from exc
    return PreparedExecution(
        model_request=ModelTaskRequest(
            task_id=payload.task_id or f"task_{uuid.uuid4().hex}",
            task_type=payload.task_type,
            database_id=payload.database_id,
            book_id=payload.book_id,
            chapter_id=payload.chapter_id,
            session_id=payload.session_id,
            user_selected_model_id=payload.user_selected_model_id,
            messages=tuple(messages),
            privacy_level="private",
            requires_json=payload.requires_json,
            requires_streaming=True,
            owner_id=owner_principal(principal.credential_role),
            context_task_id=payload.context_task_id,
            selected_asset_ids=selected_asset_ids,
        ),
        original_messages=original_messages,
        approved_context_ids=tuple(sorted(approved_context_ids)),
        selected_asset_ids=selected_asset_ids,
    )


def _prepare_recovery_route(
    payload: ModelExecuteRequest,
    prepared: PreparedExecution,
    gateway,
    recovery_owner: str,
):
    model_request = prepared.model_request
    if not payload.recovery_ticket:
        route = gateway.resolve(model_request) if hasattr(gateway, "resolve") else None
        return prepared, None, route
    try:
        ticket = prepare_recovery_execution(
            payload.recovery_ticket,
            recovery_owner,
            model_request,
        )
    except ModelRecoveryError as exc:
        raise _recovery_http_error(exc) from exc
    selected_model_id = ticket["selected_model_profile_id"]
    if payload.user_selected_model_id and payload.user_selected_model_id != selected_model_id:
        raise HTTPException(
            409,
            detail={
                "code": "RECOVERY_TARGET_MISMATCH",
                "message": "Selected model does not match the confirmed recovery ticket",
            },
        )
    model_request = replace(model_request, user_selected_model_id=selected_model_id)
    if not hasattr(gateway, "resolve"):
        raise HTTPException(
            409,
            detail={"code": "RECOVERY_UNSUPPORTED", "message": "Gateway cannot revalidate recovery"},
        )
    route = gateway.resolve(model_request)
    if (
        route.status is not RouteStatus.RESOLVED
        or route.selected_model_profile_id != selected_model_id
    ):
        raise HTTPException(
            409,
            detail={
                "code": "RECOVERY_TARGET_UNAVAILABLE",
                "message": "Confirmed model no longer satisfies routing policy",
            },
        )
    return replace(prepared, model_request=model_request), ticket, route


def _resolved_provider_model(route):
    if route is None or route.status is not RouteStatus.RESOLVED:
        return None, None
    profile = get_model_profile(route.selected_model_profile_id)
    provider = get_provider(profile["provider_id"]) if profile else None
    if not profile or not provider:
        raise HTTPException(
            409,
            detail={
                "code": "MODEL_ROUTE_STALE",
                "message": "Resolved model route no longer exists.",
            },
        )
    return provider, profile


def _enforce_resolved_policy(prepared: PreparedExecution, model_profile_id: str):
    try:
        return enforce_model_data_policy(
            model_profile_id,
            contains_original_text=any(
                bool(message["content"].strip())
                for message in prepared.original_messages
            ),
            approved_context_ids=prepared.approved_context_ids,
            selected_asset_ids=prepared.selected_asset_ids,
            estimated_payload_size=estimate_payload_size(
                prepared.model_request.messages,
                prepared.approved_context_ids,
                prepared.selected_asset_ids,
            ),
        )
    except ModelDataBoundaryError as exc:
        raise _data_boundary_http_error(exc) from exc


@router.post("/api/model-routing/data-manifests", status_code=201)
def create_model_data_manifest(
    payload: ModelExecuteRequest,
    request: Request,
    principal: EffectivePrincipal = Depends(require_model_execution),
    gateway=Depends(get_execution_gateway),
):
    if payload.data_manifest_id:
        raise HTTPException(400, "data_manifest_id is not accepted while creating a manifest")
    prepared = _prepare_execution(payload, request, principal)
    recovery_owner = owner_fingerprint(request.headers.get("x-api-key", ""))
    prepared, _, route = _prepare_recovery_route(
        payload,
        prepared,
        gateway,
        recovery_owner,
    )
    if route is None:
        raise HTTPException(
            409,
            detail={
                "code": "MODEL_ROUTE_UNAVAILABLE",
                "message": "Gateway cannot resolve a concrete provider and model.",
            },
        )
    if route.status is not RouteStatus.RESOLVED:
        raise _route_http_error(route)
    provider, profile = _resolved_provider_model(route)
    try:
        manifest = create_data_manifest(
            owner_id=owner_principal(principal.credential_role),
            task_id=prepared.model_request.task_id,
            task_type=prepared.model_request.canonical_task_type,
            database_id=prepared.model_request.database_id,
            book_id=prepared.model_request.book_id,
            chapter_id=prepared.model_request.chapter_id,
            provider_id=provider["id"],
            model_id=profile["id"],
            original_messages=prepared.original_messages,
            final_messages=prepared.model_request.messages,
            approved_context_ids=prepared.approved_context_ids,
            selected_asset_ids=prepared.selected_asset_ids,
        )
    except ModelDataBoundaryError as exc:
        raise _data_boundary_http_error(exc) from exc
    return {"protocol_version": "1.0", "manifest": manifest}


@router.get("/api/model-routing/data-manifests/{data_manifest_id}")
def read_model_data_manifest(
    data_manifest_id: str,
    principal: EffectivePrincipal = Depends(require_model_execution),
):
    try:
        manifest = get_data_manifest(
            data_manifest_id,
            owner_principal(principal.credential_role),
        )
    except ModelDataBoundaryError as exc:
        raise _data_boundary_http_error(exc) from exc
    return {"protocol_version": "1.0", "manifest": manifest}


@router.post("/api/model-routing/data-manifests/{data_manifest_id}/confirm")
def confirm_model_data_manifest(
    data_manifest_id: str,
    principal: EffectivePrincipal = Depends(require_model_execution),
):
    try:
        manifest = confirm_data_manifest(
            data_manifest_id,
            owner_principal(principal.credential_role),
        )
    except ModelDataBoundaryError as exc:
        raise _data_boundary_http_error(exc) from exc
    return {"protocol_version": "1.0", "manifest": manifest}


@router.post("/api/model-routing/recovery/{ticket_id}/confirm")
def confirm_model_recovery(
    ticket_id: str,
    payload: ModelRecoveryConfirmRequest,
    request: Request,
    _: EffectivePrincipal = Depends(require_model_execution),
):
    owner = owner_fingerprint(request.headers.get("x-api-key", ""))
    try:
        ticket = confirm_recovery_ticket(
            ticket_id,
            owner,
            payload.model_profile_id,
        )
    except ModelRecoveryError as exc:
        raise _recovery_http_error(exc) from exc
    return {
        "protocol_version": "1.0",
        "ticket_id": ticket["id"],
        "recovery_kind": ticket["recovery_kind"],
        "status": ticket["status"],
        "expires_at": ticket["expires_at"],
        "selected_model": safe_model_candidate(ticket["selected_model_profile_id"]),
    }


@router.get("/api/model-routing/tasks/{task_id}/executions")
def read_model_task_executions(
    task_id: str,
    principal: EffectivePrincipal = Depends(require_model_execution),
):
    return {
        "protocol_version": "1.0",
        "task_id": _validate_task_id(task_id),
        "executions": list_task_executions(
            task_id,
            owner_principal(principal.credential_role),
        ),
    }


@router.post("/api/model-routing/tasks/{task_id}/cancel")
def cancel_model_task(
    task_id: str,
    principal: EffectivePrincipal = Depends(require_model_execution),
):
    return {
        "protocol_version": "1.0",
        **cancel_task_executions(
            _validate_task_id(task_id),
            owner_principal(principal.credential_role),
        ),
    }


@router.post("/api/model-routing/execute-stream")
async def execute_stream(
    payload: ModelExecuteRequest,
    request: Request,
    principal: EffectivePrincipal = Depends(require_model_execution),
    gateway=Depends(get_execution_gateway),
):
    prepared = _prepare_execution(payload, request, principal)
    recovery_owner = owner_fingerprint(request.headers.get("x-api-key", ""))
    prepared, recovery_ticket, route = _prepare_recovery_route(
        payload,
        prepared,
        gateway,
        recovery_owner,
    )
    provider, profile = _resolved_provider_model(route)
    if profile:
        _enforce_resolved_policy(prepared, profile["id"])
        if is_cloud_provider(provider):
            if not payload.data_manifest_id:
                raise HTTPException(
                    409,
                    detail={
                        "code": "CLOUD_DATA_MANIFEST_REQUIRED",
                        "message": "Cloud execution requires a confirmed server-generated data manifest.",
                    },
                )
            try:
                claim_data_manifest(
                    payload.data_manifest_id,
                    owner_id=owner_principal(principal.credential_role),
                    task_id=prepared.model_request.task_id,
                    task_type=prepared.model_request.canonical_task_type,
                    database_id=prepared.model_request.database_id,
                    book_id=prepared.model_request.book_id,
                    chapter_id=prepared.model_request.chapter_id,
                    provider_id=provider["id"],
                    model_id=profile["id"],
                    original_messages=prepared.original_messages,
                    final_messages=prepared.model_request.messages,
                    approved_context_ids=prepared.approved_context_ids,
                    selected_asset_ids=prepared.selected_asset_ids,
                )
            except ModelDataBoundaryError as exc:
                raise _data_boundary_http_error(exc) from exc
        elif payload.data_manifest_id:
            try:
                claim_data_manifest(
                    payload.data_manifest_id,
                    owner_id=owner_principal(principal.credential_role),
                    task_id=prepared.model_request.task_id,
                    task_type=prepared.model_request.canonical_task_type,
                    database_id=prepared.model_request.database_id,
                    book_id=prepared.model_request.book_id,
                    chapter_id=prepared.model_request.chapter_id,
                    provider_id=provider["id"],
                    model_id=profile["id"],
                    original_messages=prepared.original_messages,
                    final_messages=prepared.model_request.messages,
                    approved_context_ids=prepared.approved_context_ids,
                    selected_asset_ids=prepared.selected_asset_ids,
                )
            except ModelDataBoundaryError as exc:
                raise _data_boundary_http_error(exc) from exc
        prepared = replace(
            prepared,
            model_request=replace(
                prepared.model_request,
                user_selected_model_id=profile["id"],
            ),
        )
    recovery_kind = recovery_ticket["recovery_kind"] if recovery_ticket else None
    if payload.recovery_ticket:
        try:
            claim_recovery_execution(
                payload.recovery_ticket,
                recovery_owner,
                prepared.model_request,
            )
        except ModelRecoveryError as exc:
            raise _recovery_http_error(exc) from exc
    return StreamingResponse(
        encode_events(
            stream_model_task(
                gateway,
                prepared.model_request,
                recovery_owner=recovery_owner,
                recovery_kind=recovery_kind,
            )
        ),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
