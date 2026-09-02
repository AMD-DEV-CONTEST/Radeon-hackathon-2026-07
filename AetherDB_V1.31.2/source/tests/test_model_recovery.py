import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest

import services.database_registry as registry
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.context_engine import owner_fingerprint
from services.db import close_connection, init_db
from services.model_execution import ModelTaskRequest
from services.model_recovery import (
    ModelRecoveryError,
    claim_recovery_execution,
    confirm_recovery_ticket,
    prepare_recovery_execution,
)
from services.model_registry import (
    create_binding,
    create_model_profile,
    create_provider,
    update_model_profile,
)
from services.model_reliability import ModelErrorCode, ModelExecutionError, RetryPolicy
from services.model_routing import (
    CredentialResolver,
    ModelRouteError,
    RouteStatus,
    RoutedModelExecutionGateway,
)
from services.model_streaming import stream_model_task
from tests.asgi_client import asgi_request


class SequenceAdapter:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.calls = []

    async def complete(self, provider, profile, messages, options):
        self.calls.append(profile["id"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"content": outcome, "usage": {}}


def setup_models(tmp_path, monkeypatch, *, bind_local=False):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    create_provider(
        {
            "id": "local-main",
            "display_name": "Local runtime",
            "provider_type": "local_ollama",
            "base_url": "http://127.0.0.1:11434",
            "api_format": "ollama_chat",
        }
    )
    create_provider(
        {
            "id": "cloud-main",
            "display_name": "Cloud provider",
            "provider_type": "openai_compatible",
            "base_url": "https://api.example.invalid/v1",
            "api_format": "openai_chat",
        }
    )
    for profile_id, provider_id, privacy in (
        ("local-main:writer", "local-main", "local_only"),
        ("cloud-main:writer", "cloud-main", "cloud_upload"),
    ):
        create_model_profile(
            {
                "id": profile_id,
                "provider_id": provider_id,
                "provider_model_name": profile_id.split(":", 1)[1],
                "display_name": profile_id,
                "model_type": "text",
                "enabled": True,
                "supports_streaming": True,
                "supports_json_mode": True,
                "privacy_level": privacy,
                "cost_level": "low",
            }
        )
    if bind_local:
        create_binding(
            {
                "id": "analysis-primary",
                "scope_type": "global",
                "task_type": "chapter_analysis",
                "target_id": "local-main:writer",
            }
        )


def model_task(content="chapter-private-marker"):
    return ModelTaskRequest(
        task_id="recovery-task",
        task_type="chapter_analysis",
        database_id="default",
        book_id="default",
        messages=({"role": "user", "content": content},),
        privacy_level="private",
        requires_json=True,
        requires_streaming=True,
    )


def gateway(adapter):
    return RoutedModelExecutionGateway(
        adapter=adapter,
        credential_resolver=CredentialResolver(env={}),
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
    )


def collect(execution, request, **kwargs):
    async def run():
        return [event async for event in stream_model_task(execution, request, **kwargs)]

    return asyncio.run(run())


def test_ambiguous_recovery_is_safe_request_bound_and_single_use(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    adapter = SequenceAdapter(["selected output"])
    execution = gateway(adapter)
    request = model_task()

    events = collect(execution, request, recovery_owner="owner-a")
    route_event = next(item for item in events if item.event == "routing_resolved")
    assert route_event.payload["status"] == "ambiguous"
    assert len(route_event.payload["candidates"]) == 2
    assert adapter.calls == []
    serialized_candidates = json.dumps(route_event.payload["candidates"])
    assert "base_url" not in serialized_candidates
    assert "credential" not in serialized_candidates

    ticket_id = route_event.payload["recovery_ticket"]
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        stored = conn.execute(
            "SELECT request_hash,candidate_model_ids_json FROM model_recovery_tickets WHERE id=?",
            (ticket_id,),
        ).fetchone()
    assert len(stored[0]) == 64
    assert "chapter-private-marker" not in json.dumps(stored)

    first = confirm_recovery_ticket(ticket_id, "owner-a", "local-main:writer")
    second = confirm_recovery_ticket(ticket_id, "owner-a", "local-main:writer")
    assert first["status"] == second["status"] == "confirmed"

    with pytest.raises(ModelRecoveryError) as mismatch:
        prepare_recovery_execution(ticket_id, "owner-a", model_task("changed request"))
    assert mismatch.value.code == "RECOVERY_REQUEST_MISMATCH"

    selected = replace(request, user_selected_model_id="local-main:writer")
    prepared = prepare_recovery_execution(ticket_id, "owner-a", selected)
    assert prepared["selected_model_profile_id"] == "local-main:writer"
    assert execution.resolve(selected).status is RouteStatus.RESOLVED
    claim_recovery_execution(ticket_id, "owner-a", selected)
    result = asyncio.run(execution.execute_resolved(selected, execution.resolve(selected)))
    assert result.model_profile_id == "local-main:writer"
    assert adapter.calls == ["local-main:writer"]
    with pytest.raises(ModelRecoveryError) as reused:
        claim_recovery_execution(ticket_id, "owner-a", selected)
    assert reused.value.code == "RECOVERY_ALREADY_USED"
    close_connection()


def test_recovery_selection_is_revalidated_after_confirmation(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    adapter = SequenceAdapter(["must not execute"])
    execution = gateway(adapter)
    request = model_task()
    events = collect(execution, request, recovery_owner="owner-a")
    ticket_id = next(
        item.payload["recovery_ticket"] for item in events if item.event == "routing_resolved"
    )
    confirm_recovery_ticket(ticket_id, "owner-a", "cloud-main:writer")
    selected = replace(request, user_selected_model_id="cloud-main:writer")
    resolved_before_disable = execution.resolve(selected)
    assert resolved_before_disable.status is RouteStatus.RESOLVED
    update_model_profile("cloud-main:writer", {"enabled": False})

    assert execution.resolve(selected).status is RouteStatus.UNAVAILABLE
    with pytest.raises(ModelRouteError):
        asyncio.run(execution.execute_resolved(selected, resolved_before_disable))
    assert adapter.calls == []
    close_connection()


def test_manual_selection_cannot_bypass_cost_policy(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    update_model_profile("cloud-main:writer", {"cost_level": "high"})
    request = replace(
        model_task(),
        user_selected_model_id="cloud-main:writer",
        max_cost_level="low",
    )
    route = gateway(SequenceAdapter()).resolve(request)
    assert route.status is RouteStatus.BLOCKED
    assert route.reason == "cost_policy"
    close_connection()


def test_local_to_cloud_fallback_requires_ticket_confirmation(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch, bind_local=True)
    failure = ModelExecutionError(ModelErrorCode.NETWORK_ERROR)
    adapter = SequenceAdapter([failure, failure, "cloud output"])
    execution = gateway(adapter)
    request = model_task()

    events = collect(execution, request, recovery_owner="owner-a")
    fallback = next(item for item in events if item.event == "fallback_required")
    assert fallback.payload["candidates"][0]["provider"]["is_local"] is False
    assert adapter.calls == ["local-main:writer", "local-main:writer"]
    ticket_id = fallback.payload["recovery_ticket"]

    with pytest.raises(ModelRecoveryError) as required:
        prepare_recovery_execution(ticket_id, "owner-a", request)
    assert required.value.code == "RECOVERY_CONFIRMATION_REQUIRED"

    confirm_recovery_ticket(ticket_id, "owner-a", "cloud-main:writer")
    selected = replace(request, user_selected_model_id="cloud-main:writer")
    claim_recovery_execution(ticket_id, "owner-a", selected)
    recovered = collect(
        execution,
        selected,
        recovery_owner="owner-a",
        recovery_kind="fallback_confirmation",
    )
    assert recovered[-1].event == "task_done"
    assert adapter.calls == ["local-main:writer", "local-main:writer", "cloud-main:writer"]
    close_connection()


def test_recovery_confirmation_endpoint_is_admin_only_and_idempotent(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    execution = gateway(SequenceAdapter())
    owner = owner_fingerprint(ADMIN_API_KEY)
    events = collect(execution, model_task(), recovery_owner=owner)
    ticket_id = next(
        item.payload["recovery_ticket"] for item in events if item.event == "routing_resolved"
    )
    path = f"/api/model-routing/recovery/{ticket_id}/confirm"
    body = {"model_profile_id": "local-main:writer"}

    assert asgi_request(app, "POST", path, json_body=body)[0] == 401
    first = asgi_request(
        app,
        "POST",
        path,
        headers={"X-API-Key": ADMIN_API_KEY},
        json_body=body,
    )
    second = asgi_request(
        app,
        "POST",
        path,
        headers={"X-API-Key": ADMIN_API_KEY},
        json_body=body,
    )
    assert first[0] == second[0] == 200
    assert first[1]["status"] == second[1]["status"] == "confirmed"
    assert "base_url" not in json.dumps(first[1])
    close_connection()


def test_execute_stream_completes_confirmed_recovery_once(tmp_path, monkeypatch):
    from api import model_execution as execution_api

    setup_models(tmp_path, monkeypatch)
    adapter = SequenceAdapter(["recovered output"])
    execution = gateway(adapter)
    app.dependency_overrides[execution_api.get_execution_gateway] = lambda: execution
    payload = {
        "task_id": "api-recovery-task",
        "task_type": "chapter_analysis",
        "database_id": "default",
        "book_id": "default",
        "messages": [{"role": "user", "content": "same request"}],
        "requires_json": True,
    }
    headers = {"X-API-Key": ADMIN_API_KEY}
    try:
        status, body = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers=headers,
            json_body=payload,
        )
        assert status == 200
        events = [json.loads(line) for line in body.splitlines()]
        route = next(item for item in events if item["event"] == "routing_resolved")
        ticket_id = route["payload"]["recovery_ticket"]
        assert adapter.calls == []

        confirm_status, _ = asgi_request(
            app,
            "POST",
            f"/api/model-routing/recovery/{ticket_id}/confirm",
            headers=headers,
            json_body={"model_profile_id": "local-main:writer"},
        )
        assert confirm_status == 200

        recovery_payload = {**payload, "recovery_ticket": ticket_id}
        recovered_status, recovered_body = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers=headers,
            json_body=recovery_payload,
        )
        assert recovered_status == 200
        recovered_events = [json.loads(line) for line in recovered_body.splitlines()]
        assert recovered_events[-1]["event"] == "task_done"
        assert adapter.calls == ["local-main:writer"]

        replay_status, replay_body = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers=headers,
            json_body=recovery_payload,
        )
        assert replay_status == 409
        assert replay_body["detail"]["code"] == "RECOVERY_ALREADY_USED"
    finally:
        app.dependency_overrides.clear()
    close_connection()
