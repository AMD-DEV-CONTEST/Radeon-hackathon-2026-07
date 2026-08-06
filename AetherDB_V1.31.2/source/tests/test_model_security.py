import json
import sqlite3
from dataclasses import replace

import pytest

import services.database_registry as registry
import services.model_tools as model_tools
from api import model_execution as execution_api
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from app.models import ContextApprovalItem, ContextMapRequest, ContextNeed
from main import app
from services.context_engine import approve_context, create_context_map, owner_principal
from services.db import close_connection, get_db, init_db
from services.model_data_boundary import (
    ModelDataBoundaryError,
    claim_data_manifest,
    confirm_data_manifest,
    create_data_manifest,
    set_model_data_policy,
)
from services.model_execution import ModelTaskResult
from services.model_registry import create_model_profile, create_provider
from services.model_routing import RouteResult, RouteStatus
from services.model_tools import (
    ModelToolError,
    ToolExecutionContext,
    execute_registered_tool,
    set_model_tool_policy,
)
from tests.asgi_client import asgi_request


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    return root


def add_model(*, local=False, supports_tools=False):
    provider_id = "local-provider" if local else "cloud-provider"
    profile_id = "local-model" if local else "cloud-model"
    create_provider(
        {
            "id": provider_id,
            "display_name": provider_id,
            "provider_type": "ollama" if local else "openai_compatible",
            "base_url": "http://127.0.0.1:11434" if local else "https://api.example.com",
            "api_format": "ollama_chat" if local else "openai_chat",
            "enabled": True,
        }
    )
    create_model_profile(
        {
            "id": profile_id,
            "provider_id": provider_id,
            "provider_model_name": "writer:latest",
            "display_name": profile_id,
            "model_type": "text",
            "enabled": True,
            "supports_streaming": True,
            "supports_tools": supports_tools,
            "privacy_level": "local_only" if local else "cloud_upload",
        }
    )
    return provider_id, profile_id


def manifest_args(provider_id, profile_id, *, original="private original passage"):
    messages = ({"role": "user", "content": original},)
    return {
        "owner_id": "role:admin",
        "task_id": "manifest-task",
        "task_type": "chapter_analysis",
        "database_id": "default",
        "book_id": "default",
        "chapter_id": None,
        "provider_id": provider_id,
        "model_id": profile_id,
        "original_messages": messages,
        "final_messages": messages,
        "approved_context_ids": (),
        "selected_asset_ids": (),
    }


def test_cloud_manifest_is_hash_only_confirmed_revalidated_and_single_use(
    tmp_path, monkeypatch
):
    setup_runtime(tmp_path, monkeypatch)
    provider_id, profile_id = add_model()
    args = manifest_args(provider_id, profile_id)

    manifest = create_data_manifest(**args)
    assert manifest["status"] == "pending"
    assert manifest["cloud_confirmation_required"] is True
    assert "private original passage" not in json.dumps(manifest)
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        stored = conn.execute(
            "SELECT * FROM model_data_manifests WHERE data_manifest_id=?",
            (manifest["data_manifest_id"],),
        ).fetchone()
    assert "private original passage" not in repr(stored)

    with pytest.raises(ModelDataBoundaryError) as unconfirmed:
        claim_data_manifest(manifest["data_manifest_id"], **args)
    assert unconfirmed.value.code == "DATA_MANIFEST_CONFIRMATION_REQUIRED"

    confirm_data_manifest(manifest["data_manifest_id"], "role:admin")
    changed = {
        **args,
        "original_messages": ({"role": "user", "content": "changed"},),
        "final_messages": ({"role": "user", "content": "changed"},),
    }
    with pytest.raises(ModelDataBoundaryError) as mismatch:
        claim_data_manifest(manifest["data_manifest_id"], **changed)
    assert mismatch.value.code == "DATA_MANIFEST_MISMATCH"

    claimed = claim_data_manifest(manifest["data_manifest_id"], **args)
    assert claimed["status"] == "consumed"
    with pytest.raises(ModelDataBoundaryError) as replay:
        claim_data_manifest(manifest["data_manifest_id"], **args)
    assert replay.value.code == "DATA_MANIFEST_ALREADY_USED"
    close_connection()


def test_cloud_policy_blocks_context_and_cross_book_media(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    provider_id, profile_id = add_model()
    db = get_db("default")
    db.execute("INSERT INTO books(book_id,title) VALUES ('other','Other')")
    db.execute(
        """INSERT INTO media_assets(
               asset_id,database_id,book_id,modality,mime_type,relative_path,
               original_filename,content_hash,file_size_bytes,source_type,lifecycle_status
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "asset-other",
            "default",
            "other",
            "image",
            "image/png",
            "assets/other.png",
            "other.png",
            "a" * 64,
            10,
            "imported",
            "approved",
        ),
    )
    db.commit()
    db.close()

    args = manifest_args(provider_id, profile_id)
    with pytest.raises(ModelDataBoundaryError) as context_blocked:
        create_data_manifest(**{**args, "approved_context_ids": ("ctx-approved",)})
    assert context_blocked.value.code == "APPROVED_CONTEXT_BLOCKED"

    set_model_data_policy(
        profile_id,
        permission_tier="B_CONTEXT_ENHANCED",
        allow_original_text=True,
        allow_approved_context=True,
        allow_selected_media=True,
        max_payload_bytes=2 * 1024 * 1024,
        updated_by="role:admin",
    )
    with pytest.raises(ModelDataBoundaryError) as asset_blocked:
        create_data_manifest(**{**args, "selected_asset_ids": ("asset-other",)})
    assert asset_blocked.value.code == "ASSET_SCOPE_INVALID"
    close_connection()


class RecordingResolvedGateway:
    def __init__(self, model_profile_id):
        self.model_profile_id = model_profile_id
        self.calls = []

    def resolve(self, _request):
        return RouteResult(
            status=RouteStatus.RESOLVED,
            selected_model_profile_id=self.model_profile_id,
            candidates=(),
            reason="test_route",
            requires_user_confirmation=False,
        )

    async def execute_resolved(self, request, _route):
        self.calls.append(request)
        return ModelTaskResult(
            task_id=request.task_id,
            model_profile_id=self.model_profile_id,
            provider_id="cloud-provider",
            provider_model_name="writer:latest",
            content="completed",
        )


def test_cloud_execution_requires_exact_server_manifest(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    _, profile_id = add_model()
    gateway = RecordingResolvedGateway(profile_id)
    app.dependency_overrides[execution_api.get_execution_gateway] = lambda: gateway
    payload = {
        "task_id": "endpoint-manifest-task",
        "task_type": "chapter_analysis",
        "database_id": "default",
        "book_id": "default",
        "messages": [{"role": "user", "content": "selected chapter text"}],
    }
    try:
        missing_status, missing = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers={"X-API-Key": ADMIN_API_KEY},
            json_body=payload,
        )
        assert missing_status == 409
        assert missing["detail"]["code"] == "CLOUD_DATA_MANIFEST_REQUIRED"
        assert gateway.calls == []

        status, created = asgi_request(
            app,
            "POST",
            "/api/model-routing/data-manifests",
            headers={"X-API-Key": ADMIN_API_KEY},
            json_body=payload,
        )
        assert status == 201
        manifest = created["manifest"]
        assert manifest["task_id"] == payload["task_id"]
        assert "selected chapter text" not in json.dumps(created)

        assert asgi_request(
            app,
            "POST",
            f"/api/model-routing/data-manifests/{manifest['data_manifest_id']}/confirm",
            headers={"X-API-Key": ADMIN_API_KEY},
        )[0] == 200

        changed = {
            **payload,
            "messages": [{"role": "user", "content": "different text"}],
            "data_manifest_id": manifest["data_manifest_id"],
        }
        changed_status, changed_body = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers={"X-API-Key": ADMIN_API_KEY},
            json_body=changed,
        )
        assert changed_status == 409
        assert changed_body["detail"]["code"] == "DATA_MANIFEST_MISMATCH"
        assert gateway.calls == []

        exact = {**payload, "data_manifest_id": manifest["data_manifest_id"]}
        exact_status, stream = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers={"X-API-Key": ADMIN_API_KEY},
            json_body=exact,
        )
        assert exact_status == 200
        assert json.loads(stream.splitlines()[-1])["event"] == "task_done"
        assert len(gateway.calls) == 1
    finally:
        app.dependency_overrides.clear()
        close_connection()


def setup_tool_model(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    _, profile_id = add_model(local=True, supports_tools=True)
    set_model_data_policy(
        profile_id,
        permission_tier="C_RESTRICTED_TOOLS",
        allow_original_text=True,
        allow_approved_context=True,
        allow_selected_media=True,
        max_payload_bytes=2 * 1024 * 1024,
        updated_by="role:admin",
    )
    return profile_id


def test_controlled_tools_reject_scope_injection_and_never_apply_writes(
    tmp_path, monkeypatch
):
    profile_id = setup_tool_model(tmp_path, monkeypatch)
    set_model_tool_policy(
        profile_id, "search_entities", enabled=True, updated_by="role:admin"
    )
    set_model_tool_policy(
        profile_id, "propose_changeset", enabled=True, updated_by="role:admin"
    )
    db = get_db("default")
    db.execute("INSERT INTO books(book_id,title) VALUES ('other','Other')")
    db.execute(
        "INSERT INTO entities(entity_id,entity_type,title,content,book_id) VALUES (?,?,?,?,?)",
        ("ENTITY_ALLOWED", "character", "Shared Name", "allowed", "default"),
    )
    db.execute(
        "INSERT INTO entities(entity_id,entity_type,title,content,book_id) VALUES (?,?,?,?,?)",
        ("ENTITY_OTHER", "character", "Shared Name", "private other", "other"),
    )
    db.commit()
    before = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    db.close()
    context = ToolExecutionContext(
        task_id="tool-task",
        model_profile_id=profile_id,
        database_id="default",
        book_id="default",
        chapter_id=None,
        owner_id="role:admin",
    )

    result = execute_registered_tool(
        context, "search_entities", {"query": "Shared Name", "limit": 10}
    )
    assert [item["entity_id"] for item in result["result"]["items"]] == [
        "ENTITY_ALLOWED"
    ]
    with pytest.raises(ModelToolError) as scope_injection:
        execute_registered_tool(
            context,
            "search_entities",
            {"query": "Shared Name", "database_id": "other"},
        )
    assert scope_injection.value.code == "TOOL_SCHEMA_INVALID"
    with pytest.raises(ModelToolError) as shell_attempt:
        execute_registered_tool(context, "shell", {"command": "whoami"})
    assert shell_attempt.value.code == "TOOL_NOT_REGISTERED"

    proposal = execute_registered_tool(
        context,
        "propose_changeset",
        {
            "entities": [
                {"entity_type": "character", "title": "Proposed", "content": "draft"}
            ],
            "relations": [],
        },
    )
    assert proposal["result"]["write_status"] == "not_applied"
    db = get_db("default")
    assert db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == before
    db.close()
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        audits = conn.execute(
            "SELECT input_hash,output_hash,status FROM model_tool_executions"
        ).fetchall()
    assert audits
    assert all(len(row[0]) == 64 for row in audits)
    assert "Shared Name" not in repr(audits)
    close_connection()


def test_controlled_context_tool_reads_only_approved_candidates(tmp_path, monkeypatch):
    profile_id = setup_tool_model(tmp_path, monkeypatch)
    set_model_tool_policy(
        profile_id, "read_approved_context", enabled=True, updated_by="role:admin"
    )
    db = get_db("default")
    db.execute(
        "INSERT INTO entities(entity_id,entity_type,title,content,ai_summary,book_id) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ENTITY_CONTEXT",
            "character",
            "Context Name",
            "approved context body",
            "context summary",
            "default",
        ),
    )
    db.commit()
    db.close()
    owner = owner_principal("admin")
    context_map = create_context_map(
        ContextMapRequest(
            task_id="approved-tool-context",
            task_type="world_consistency",
            database_id="default",
            book_id="default",
            needs=[
                ContextNeed(
                    context_type="mentioned_entities",
                    query="Context Name",
                    reason="test",
                )
            ],
        ),
        owner,
    )
    candidate_id = context_map["candidates"][0]["candidate_id"]
    approve_context(
        "default",
        "approved-tool-context",
        [ContextApprovalItem(candidate_id=candidate_id, approved=True)],
        owner,
    )
    context = ToolExecutionContext(
        task_id="tool-context-task",
        model_profile_id=profile_id,
        database_id="default",
        book_id="default",
        chapter_id=None,
        owner_id=owner,
        context_task_id="approved-tool-context",
    )
    result = execute_registered_tool(
        context,
        "read_approved_context",
        {"candidate_ids": [candidate_id]},
    )
    assert result["result"]["items"][0]["content"] == "context summary"
    assert "approved context body" not in json.dumps(result)
    with pytest.raises(ModelToolError) as rejected:
        execute_registered_tool(
            context,
            "read_approved_context",
            {"candidate_ids": ["ctx-" + "0" * 32]},
        )
    assert rejected.value.code == "TOOL_CONTEXT_NOT_APPROVED"
    close_connection()


def test_tool_output_schema_and_security_api_authorization(tmp_path, monkeypatch):
    profile_id = setup_tool_model(tmp_path, monkeypatch)
    set_model_tool_policy(
        profile_id, "search_entities", enabled=True, updated_by="role:admin"
    )
    context = ToolExecutionContext(
        task_id="schema-task",
        model_profile_id=profile_id,
        database_id="default",
        book_id="default",
        chapter_id=None,
        owner_id="role:admin",
    )
    original = model_tools.TOOL_DEFINITIONS["search_entities"]
    monkeypatch.setitem(
        model_tools.TOOL_DEFINITIONS,
        "search_entities",
        replace(original, handler=lambda _context, _request: {"unexpected": True}),
    )
    with pytest.raises(ModelToolError) as invalid_output:
        execute_registered_tool(context, "search_entities", {"query": "anything"})
    assert invalid_output.value.code == "TOOL_SCHEMA_INVALID"

    assert asgi_request(
        app,
        "GET",
        "/api/model-security/tools",
    )[0] == 401
    local_owner_status, _ = asgi_request(
        app,
        "GET",
        "/api/model-security/tools",
        headers={"X-API-Key": USER_API_KEY},
    )
    assert local_owner_status == 200
    admin_status, body = asgi_request(
        app,
        "GET",
        "/api/model-security/tools",
        headers={"X-API-Key": ADMIN_API_KEY},
    )
    assert admin_status == 200
    assert {item["tool_name"] for item in body["tools"]} == set(
        model_tools.TOOL_DEFINITIONS
    )
    close_connection()
