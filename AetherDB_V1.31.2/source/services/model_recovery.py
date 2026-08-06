"""Short-lived, request-bound recovery tickets for model execution."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from services.database_registry import _get_registry_conn
from services.model_registry import get_model_profile, get_provider


RECOVERY_KINDS = {"ambiguous_selection", "fallback_confirmation"}
class ModelRecoveryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def request_fingerprint(request) -> str:
    """Hash execution-affecting input without persisting prompt or evidence text."""
    payload = {
        "task_id": request.task_id,
        "task_type": request.task_type,
        "database_id": request.database_id,
        "book_id": request.book_id,
        "chapter_id": request.chapter_id,
        "session_id": request.session_id,
        "messages": list(request.messages),
        "privacy_level": request.privacy_level,
        "max_cost_level": request.max_cost_level,
        "requires_json": request.requires_json,
        "requires_streaming": request.requires_streaming,
        "context_task_id": request.context_task_id,
        "selected_asset_ids": list(request.selected_asset_ids),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_model_candidate(model_profile_id: str) -> dict | None:
    profile = get_model_profile(model_profile_id)
    if not profile:
        return None
    provider = get_provider(profile["provider_id"])
    if not provider:
        return None
    provider_enabled = bool(provider["enabled"])
    profile_enabled = bool(profile["enabled"])
    available = (
        provider_enabled
        and profile_enabled
        and provider["health_status"] not in {"unhealthy", "blocked"}
        and profile["health_status"] not in {"unhealthy", "blocked"}
        and profile["remote_status"] not in {"missing", "unavailable"}
    )
    return {
        "model_profile_id": profile["id"],
        "display_name": profile["display_name"],
        "provider": {
            "id": provider["id"],
            "display_name": provider["display_name"],
            "provider_type": provider["provider_type"],
            "is_local": provider["provider_type"] in {"local", "local_ollama", "ollama"},
        },
        "model_type": profile["model_type"],
        "capabilities": {
            "streaming": bool(profile["supports_streaming"]),
            "tools": bool(profile["supports_tools"]),
            "json_mode": bool(profile["supports_json_mode"]),
        },
        "privacy_level": profile["privacy_level"],
        "cost_level": profile["cost_level"],
        "health_status": profile["health_status"],
        "available": available,
    }


def safe_model_candidates(model_profile_ids) -> list[dict]:
    return [item for profile_id in model_profile_ids if (item := safe_model_candidate(profile_id))]


def _ticket_dict(row) -> dict:
    result = dict(row)
    result["candidate_model_ids"] = tuple(json.loads(result.pop("candidate_model_ids_json")))
    return result


def create_recovery_ticket(
    recovery_kind: str,
    request,
    candidate_model_ids,
    owner_fingerprint: str,
    *,
    source_model_profile_id: str | None = None,
    error_code: str | None = None,
    ttl_seconds: int = 300,
) -> dict:
    if recovery_kind not in RECOVERY_KINDS:
        raise ValueError("Unsupported recovery kind")
    candidates = tuple(dict.fromkeys(candidate_model_ids))[:5]
    if not candidates:
        raise ValueError("Recovery candidates are required")
    now = _now()
    request_hash = request_fingerprint(request)
    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM model_recovery_tickets WHERE owner_fingerprint=? "
            "AND request_hash=? AND recovery_kind=? AND status IN ('pending','confirmed') "
            "ORDER BY created_at DESC",
            (owner_fingerprint, request_hash, recovery_kind),
        ).fetchall()
        for row in rows:
            stored_candidates = tuple(json.loads(row["candidate_model_ids_json"]))
            same_candidates = stored_candidates == candidates
            same_source = row["source_model_profile_id"] == source_model_profile_id
            if _parse(row["expires_at"]) > now and same_candidates and same_source:
                conn.commit()
                return _ticket_dict(row)
            conn.execute(
                "UPDATE model_recovery_tickets SET status='superseded' WHERE id=?",
                (row["id"],),
            )
        ticket_id = uuid.uuid4().hex
        created_at = _iso(now)
        expires_at = _iso(now + timedelta(seconds=max(30, min(ttl_seconds, 900))))
        conn.execute(
            "INSERT INTO model_recovery_tickets "
            "(id,recovery_kind,owner_fingerprint,request_hash,task_type,"
            "source_model_profile_id,candidate_model_ids_json,error_code,status,"
            "expires_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                ticket_id,
                recovery_kind,
                owner_fingerprint,
                request_hash,
                request.task_type,
                source_model_profile_id,
                json.dumps(candidates, separators=(",", ":")),
                error_code,
                "pending",
                expires_at,
                created_at,
            ),
        )
        conn.commit()
        return _ticket_dict(
            conn.execute("SELECT * FROM model_recovery_tickets WHERE id=?", (ticket_id,)).fetchone()
        )
    finally:
        conn.close()


def get_recovery_ticket(ticket_id: str, owner_fingerprint: str) -> dict:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT * FROM model_recovery_tickets WHERE id=? AND owner_fingerprint=?",
            (ticket_id, owner_fingerprint),
        ).fetchone()
        if not row:
            raise ModelRecoveryError("RECOVERY_TICKET_NOT_FOUND", "Recovery ticket was not found")
        ticket = _ticket_dict(row)
        if ticket["status"] != "consumed" and _parse(ticket["expires_at"]) <= _now():
            conn.execute(
                "UPDATE model_recovery_tickets SET status='expired' WHERE id=?",
                (ticket_id,),
            )
            conn.commit()
            raise ModelRecoveryError("RECOVERY_TICKET_EXPIRED", "Recovery ticket has expired")
        return ticket
    finally:
        conn.close()


def confirm_recovery_ticket(
    ticket_id: str,
    owner_fingerprint: str,
    model_profile_id: str,
) -> dict:
    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM model_recovery_tickets WHERE id=? AND owner_fingerprint=?",
            (ticket_id, owner_fingerprint),
        ).fetchone()
        if not row:
            raise ModelRecoveryError("RECOVERY_TICKET_NOT_FOUND", "Recovery ticket was not found")
        ticket = _ticket_dict(row)
        if _parse(ticket["expires_at"]) <= _now() and ticket["status"] != "consumed":
            conn.execute("UPDATE model_recovery_tickets SET status='expired' WHERE id=?", (ticket_id,))
            conn.commit()
            raise ModelRecoveryError("RECOVERY_TICKET_EXPIRED", "Recovery ticket has expired")
        if model_profile_id not in ticket["candidate_model_ids"]:
            raise ModelRecoveryError("RECOVERY_TARGET_NOT_ALLOWED", "Selected model is not a recovery candidate")
        selected = ticket.get("selected_model_profile_id")
        if selected and selected != model_profile_id:
            raise ModelRecoveryError("RECOVERY_ALREADY_CONFIRMED", "Recovery ticket already selected another model")
        if ticket["status"] in {"expired"}:
            raise ModelRecoveryError("RECOVERY_TICKET_EXPIRED", "Recovery ticket has expired")
        if ticket["status"] not in {"pending", "confirmed", "consumed"}:
            raise ModelRecoveryError("RECOVERY_TICKET_INVALID", "Recovery ticket cannot be confirmed")
        if ticket["status"] == "pending":
            conn.execute(
                "UPDATE model_recovery_tickets SET status='confirmed',"
                "selected_model_profile_id=?,confirmed_at=? WHERE id=?",
                (model_profile_id, _iso(_now()), ticket_id),
            )
        conn.commit()
        return _ticket_dict(
            conn.execute("SELECT * FROM model_recovery_tickets WHERE id=?", (ticket_id,)).fetchone()
        )
    finally:
        conn.close()


def prepare_recovery_execution(ticket_id: str, owner_fingerprint: str, request) -> dict:
    ticket = get_recovery_ticket(ticket_id, owner_fingerprint)
    if ticket["status"] == "consumed":
        raise ModelRecoveryError("RECOVERY_ALREADY_USED", "Recovery ticket has already been used")
    if ticket["status"] != "confirmed" or not ticket.get("selected_model_profile_id"):
        raise ModelRecoveryError("RECOVERY_CONFIRMATION_REQUIRED", "Recovery ticket requires confirmation")
    if ticket["request_hash"] != request_fingerprint(request):
        raise ModelRecoveryError("RECOVERY_REQUEST_MISMATCH", "Recovery ticket does not match this request")
    selected = ticket["selected_model_profile_id"]
    if request.user_selected_model_id not in {None, selected}:
        raise ModelRecoveryError("RECOVERY_TARGET_MISMATCH", "Request selected another model")
    return ticket


def claim_recovery_execution(ticket_id: str, owner_fingerprint: str, request) -> dict:
    expected = prepare_recovery_execution(ticket_id, owner_fingerprint, request)
    if request.user_selected_model_id != expected["selected_model_profile_id"]:
        raise ModelRecoveryError("RECOVERY_TARGET_MISMATCH", "Confirmed model must be selected")
    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE model_recovery_tickets SET status='consumed',consumed_at=? "
            "WHERE id=? AND owner_fingerprint=? AND status='confirmed' AND request_hash=? ",
            (_iso(_now()), ticket_id, owner_fingerprint, expected["request_hash"]),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise ModelRecoveryError("RECOVERY_ALREADY_USED", "Recovery ticket has already been used")
        conn.commit()
        return _ticket_dict(
            conn.execute("SELECT * FROM model_recovery_tickets WHERE id=?", (ticket_id,)).fetchone()
        )
    finally:
        conn.close()
