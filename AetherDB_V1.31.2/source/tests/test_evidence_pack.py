import json
import sqlite3

import pytest
from pydantic import ValidationError

import services.database_registry as registry
from app.dependencies.auth import USER_API_KEY
from app.models import (
    ContextApprovalItem,
    ContextMapRequest,
    ContextNeed,
    TokenBudget,
)
from services.context_engine import (
    approve_context,
    build_evidence_messages,
    build_evidence_pack,
    create_context_map,
    owner_fingerprint,
    owner_principal,
)
from services.db import close_connection, get_db, init_db
from services.model_execution import ModelTaskResult
from api import model_execution as execution_api
from main import app
from tests.asgi_client import asgi_request


def setup_context(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    db = get_db("default")
    for entity_id, title, summary in (
        ("CHR_REQUIRED", "林川", "必须证据"),
        ("LOC_OPTIONAL", "北城", "未审批证据"),
    ):
        db.execute(
            "INSERT INTO entities(entity_id,entity_type,title,content,ai_summary,book_id) VALUES (?,?,?,?,?,?)",
            (entity_id, "character", title, summary, summary, "default"),
        )
    db.commit()
    db.close()
    owner = owner_fingerprint("owner")
    context_map = create_context_map(
        ContextMapRequest(
            task_id="evidence-task",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            needs=[
                ContextNeed(context_type="mentioned_entities", query="林川", reason="required", required=True),
                ContextNeed(context_type="mentioned_entities", query="北城", reason="optional", required=False),
            ],
        ),
        owner,
    )
    return owner, context_map


def budget(evidence=1000):
    return TokenBudget(
        total_context_tokens=4096,
        reserved_instruction=500,
        reserved_current_text=500,
        reserved_evidence=evidence,
        reserved_output=1000,
    )


def test_only_server_approved_candidates_enter_evidence(tmp_path, monkeypatch):
    owner, context_map = setup_context(tmp_path, monkeypatch)
    assert all("content_snapshot" not in item for item in context_map["candidates"])
    assert all("source_hash" not in item for item in context_map["candidates"])
    required = next(item for item in context_map["candidates"] if item["source_id"] == "CHR_REQUIRED")
    approve_context(
        "default",
        "evidence-task",
        [ContextApprovalItem(candidate_id=required["candidate_id"], approved=True)],
        owner,
    )

    pack = build_evidence_pack("default", "evidence-task", owner, budget())
    assert [item["source_id"] for item in pack["items"]] == ["CHR_REQUIRED"]
    serialized = json.dumps(pack, ensure_ascii=False)
    assert "必须证据" in serialized
    assert "未审批证据" not in serialized

    messages = build_evidence_messages(
        system_core="system core",
        task="check",
        current_text="current",
        evidence_pack=pack,
        output_contract="json",
    )
    assert "untrusted reference data" in messages[0]["content"]
    assert "必须证据" in messages[1]["content"]
    assert "未审批证据" not in messages[1]["content"]
    close_connection()


def test_required_priority_is_not_crowded_out_by_optional_items(tmp_path, monkeypatch):
    owner, context_map = setup_context(tmp_path, monkeypatch)
    approve_context(
        "default",
        "evidence-task",
        [
            ContextApprovalItem(candidate_id=item["candidate_id"], approved=True)
            for item in context_map["candidates"]
        ],
        owner,
    )
    pack = build_evidence_pack("default", "evidence-task", owner, budget(evidence=10))
    assert pack["items"][0]["source_id"] == "CHR_REQUIRED"
    close_connection()


def test_tampered_server_snapshot_is_rejected(tmp_path, monkeypatch):
    owner, context_map = setup_context(tmp_path, monkeypatch)
    candidate = context_map["candidates"][0]
    approve_context(
        "default",
        "evidence-task",
        [ContextApprovalItem(candidate_id=candidate["candidate_id"], approved=True)],
        owner,
    )
    with sqlite3.connect(registry.get_db_path("default")) as conn:
        conn.execute(
            "UPDATE context_candidates SET content_snapshot='tampered' WHERE candidate_id=?",
            (candidate["candidate_id"],),
        )
        conn.commit()
    with pytest.raises(ValueError):
        build_evidence_pack("default", "evidence-task", owner, budget())
    close_connection()


def test_invalid_total_token_budget_is_rejected():
    with pytest.raises(ValidationError):
        TokenBudget(
            total_context_tokens=1024,
            reserved_instruction=500,
            reserved_current_text=500,
            reserved_evidence=500,
            reserved_output=500,
        )


def test_local_owner_user_stream_rebuilds_approved_evidence_server_side(tmp_path, monkeypatch):
    owner, context_map = setup_context(tmp_path, monkeypatch)
    user_owner = owner_principal("user")
    with sqlite3.connect(registry.get_db_path("default")) as conn:
        conn.execute(
            "UPDATE context_tasks SET owner_id=? WHERE task_id='evidence-task'",
            (user_owner,),
        )
        conn.commit()
    required = next(item for item in context_map["candidates"] if item["source_id"] == "CHR_REQUIRED")
    approve_context(
        "default",
        "evidence-task",
        [ContextApprovalItem(candidate_id=required["candidate_id"], approved=True)],
        user_owner,
    )

    captured = []

    class CapturingGateway:
        async def execute(self, request):
            captured.extend(request.messages)
            return ModelTaskResult(
                task_id=request.task_id,
                model_profile_id="model-1",
                provider_id="provider-1",
                content="ok",
            )

    app.dependency_overrides[execution_api.get_execution_gateway] = lambda: CapturingGateway()
    body = {
        "task_id": "evidence-execution",
        "task_type": "world_consistency",
        "database_id": "default",
        "book_id": "default",
        "messages": [{"role": "user", "content": "check"}],
        "context_task_id": "evidence-task",
        "evidence_budget": budget().model_dump(),
    }
    try:
        status, _ = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers={"X-API-Key": USER_API_KEY},
            json_body=body,
        )
    finally:
        app.dependency_overrides.clear()
    assert status == 200
    messages = json.dumps(captured, ensure_ascii=False)
    assert "必须证据" in messages
    assert "未审批证据" not in messages
    close_connection()
