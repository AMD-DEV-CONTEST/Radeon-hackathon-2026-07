import asyncio
import json
import sqlite3
import threading
import time

import pytest

import services.database_registry as registry
import services.ollama_execution as execution_module
from services.db import close_connection, get_db, init_db
from services.model_data_boundary import set_model_data_policy
from services.model_execution import ModelTaskRequest
from services.model_registry import create_model_profile, create_provider
from services.model_reliability import ModelErrorCode, ModelExecutionError
from services.model_runtime.contracts import AdmissionStatus
from services.model_routing import (
    CredentialResolver,
    ExistingProviderAdapter,
    RoutedModelExecutionGateway,
)
from services.model_tools import set_model_tool_policy
from services.ollama_execution import (
    OllamaExecutionCoordinator,
    cancel_task_executions,
    get_ollama_execution,
    list_ollama_executions,
    recover_interrupted_ollama_executions,
)


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    provider = create_provider(
        {
            "id": "ollama-test",
            "display_name": "Ollama test",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "api_format": "ollama_chat",
            "enabled": True,
        }
    )
    profile = create_model_profile(
        {
            "id": "ollama-test:writer",
            "provider_id": provider["id"],
            "provider_model_name": "writer:latest",
            "display_name": "Writer",
            "model_type": "text",
            "enabled": True,
            "supports_streaming": True,
            "supports_tools": True,
            "privacy_level": "local_only",
        }
    )
    return provider, profile


def model_request(**updates):
    data = {
        "task_id": "ollama-execution-task",
        "task_type": "chapter_analysis",
        "database_id": "default",
        "book_id": "default",
        "messages": ({"role": "user", "content": "write a scene"},),
        "owner_id": "role:admin",
    }
    data.update(updates)
    return ModelTaskRequest(**data)


class FakeDecision:
    def __init__(self, status, *, reason="REMOTE_RUNTIME_ADMITTED", lease_id=None):
        self.status = status
        self.reason_code = reason
        self.lease_id = lease_id

    def model_dump(self, mode=None):
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "lease_id": self.lease_id,
            "runtime_id": "ollama:test-runtime",
        }


class FakeScheduler:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0
        self.released = []
        self.heartbeats = []
        self.known_leases = []

    def evaluate(self, _request, acquire=False):
        index = min(self.calls, len(self.decisions) - 1)
        self.calls += 1
        return self.decisions[index]

    def heartbeat_lease(self, lease_id):
        self.heartbeats.append(lease_id)
        return {"id": lease_id}

    def release_lease(self, lease_id, reason="RELEASED"):
        self.released.append((lease_id, reason))
        return {"id": lease_id}

    def list_leases(self, active_only=False):
        return list(self.known_leases)


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def iter_lines(self):
        for chunk in self.chunks:
            if self.closed:
                return
            yield json.dumps(chunk).encode("utf-8")

    def close(self):
        self.closed = True


class SequenceTransport:
    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.payloads = []

    def open_stream(self, _base_url, payload):
        self.payloads.append(payload)
        return FakeResponse(self.rounds.pop(0))


def runtime_ready(_provider):
    return {
        "running": True,
        "api_compatible": True,
        "runtime_id": "ollama:test-runtime",
    }


def test_ollama_execution_queues_then_completes_with_owned_lease(
    tmp_path, monkeypatch
):
    provider, profile = setup_runtime(tmp_path, monkeypatch)
    scheduler = FakeScheduler(
        [
            FakeDecision(
                AdmissionStatus.QUEUED,
                reason="REMOTE_RUNTIME_BUSY",
            ),
            FakeDecision(
                AdmissionStatus.ADMITTED,
                lease_id="lease-owned",
            ),
        ]
    )
    transport = SequenceTransport(
        [
            {
                "message": {"content": "final text", "thinking": "brief thought"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 3,
            }
        ]
    )
    coordinator = OllamaExecutionCoordinator(
        scheduler=scheduler,
        transport=transport,
        runtime_probe=runtime_ready,
        poll_interval_seconds=0.05,
    )

    result = asyncio.run(
        coordinator.execute(provider, profile, model_request(), {})
    )

    assert result["content"] == "final text"
    assert result["thinking_content"] == "brief thought"
    assert result["execution_evidence"]["resource_lease_id"] == "lease-owned"
    task = list_ollama_executions()[0]
    assert task["status"] == "completed"
    assert task["queue_reason"] is None
    assert task["prompt_tokens"] == 5
    assert task["output_tokens"] == 3
    assert scheduler.released == [
        ("lease-owned", "OLLAMA_EXECUTION_COMPLETED")
    ]
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        stored = conn.execute(
            "SELECT request_hash,response_hash FROM ollama_execution_tasks"
        ).fetchone()
    assert len(stored[0]) == len(stored[1]) == 64
    assert "write a scene" not in repr(stored)
    close_connection()


def test_existing_gateway_routes_ollama_only_through_execution_coordinator(
    tmp_path, monkeypatch
):
    _provider, profile = setup_runtime(tmp_path, monkeypatch)

    class StubCoordinator:
        def __init__(self):
            self.calls = []

        async def execute(self, provider, selected_profile, request, options):
            self.calls.append((provider, selected_profile, request, options))
            return {
                "content": "coordinated",
                "usage": {"prompt_eval_count": 2, "eval_count": 1},
                "execution_evidence": {
                    "ollama_execution_id": "execution-stub",
                    "resource_lease_id": "lease-stub",
                },
            }

    coordinator = StubCoordinator()
    monkeypatch.setattr(execution_module, "_coordinator", coordinator)
    gateway = RoutedModelExecutionGateway(
        adapter=ExistingProviderAdapter(),
        credential_resolver=CredentialResolver(env={}),
    )
    result = asyncio.run(
        gateway.execute(
            model_request(
                user_selected_model_id=profile["id"],
                privacy_level="local_only",
            )
        )
    )

    assert result.content == "coordinated"
    assert len(coordinator.calls) == 1
    assert result.execution_evidence["ollama_execution_id"] == "execution-stub"
    assert result.execution_evidence["resource_lease_id"] == "lease-stub"
    close_connection()


def test_ollama_tool_loop_uses_only_registered_server_scoped_tool(
    tmp_path, monkeypatch
):
    provider, profile = setup_runtime(tmp_path, monkeypatch)
    set_model_data_policy(
        profile["id"],
        permission_tier="C_RESTRICTED_TOOLS",
        allow_original_text=True,
        allow_approved_context=True,
        allow_selected_media=True,
        max_payload_bytes=2 * 1024 * 1024,
        updated_by="role:admin",
    )
    set_model_tool_policy(
        profile["id"],
        "search_entities",
        enabled=True,
        updated_by="role:admin",
    )
    db = get_db("default")
    db.execute("INSERT INTO books(book_id,title) VALUES ('other','Other')")
    db.execute(
        "INSERT INTO entities(entity_id,entity_type,title,content,book_id) "
        "VALUES (?,?,?,?,?)",
        ("ENTITY_ALLOWED", "character", "Shared Name", "allowed", "default"),
    )
    db.execute(
        "INSERT INTO entities(entity_id,entity_type,title,content,book_id) "
        "VALUES (?,?,?,?,?)",
        ("ENTITY_OTHER", "character", "Shared Name", "other private", "other"),
    )
    db.commit()
    db.close()
    transport = SequenceTransport(
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "index": 0,
                                "name": "search_entities",
                                "arguments": {"query": "Shared Name", "limit": 10},
                            },
                        }
                    ],
                },
                "done": True,
                "prompt_eval_count": 4,
                "eval_count": 1,
            }
        ],
        [
            {
                "message": {"content": "used approved result"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 7,
                "eval_count": 3,
            }
        ],
    )
    scheduler = FakeScheduler(
        [FakeDecision(AdmissionStatus.ADMITTED, lease_id="lease-tool")]
    )
    coordinator = OllamaExecutionCoordinator(
        scheduler=scheduler,
        transport=transport,
        runtime_probe=runtime_ready,
    )

    result = asyncio.run(
        coordinator.execute(provider, profile, model_request(), {})
    )

    assert result["content"] == "used approved result"
    assert transport.payloads[0]["tools"][0]["function"]["name"] == "search_entities"
    tool_message = next(
        message
        for message in transport.payloads[1]["messages"]
        if message["role"] == "tool"
    )
    assert "ENTITY_ALLOWED" in tool_message["content"]
    assert "ENTITY_OTHER" not in tool_message["content"]
    task = list_ollama_executions()[0]
    assert task["tool_rounds"] == 1
    assert task["tool_calls"] == 1
    close_connection()


class BlockingResponse:
    def __init__(self):
        self.started = threading.Event()
        self.closed = threading.Event()

    def iter_lines(self):
        self.started.set()
        while not self.closed.wait(0.02):
            continue
        return
        yield

    def close(self):
        self.closed.set()


class BlockingTransport:
    def __init__(self):
        self.response = BlockingResponse()

    def open_stream(self, _base_url, _payload):
        return self.response


def test_cancel_closes_only_aetherdb_request_and_releases_owned_lease(
    tmp_path, monkeypatch
):
    provider, profile = setup_runtime(tmp_path, monkeypatch)
    scheduler = FakeScheduler(
        [FakeDecision(AdmissionStatus.ADMITTED, lease_id="lease-cancel")]
    )
    transport = BlockingTransport()
    coordinator = OllamaExecutionCoordinator(
        scheduler=scheduler,
        transport=transport,
        runtime_probe=runtime_ready,
    )

    async def scenario():
        running = asyncio.create_task(
            coordinator.execute(provider, profile, model_request(), {})
        )
        for _ in range(100):
            tasks = list_ollama_executions()
            if tasks and transport.response.started.is_set():
                break
            await asyncio.sleep(0.01)
        cancelled = cancel_task_executions(
            "ollama-execution-task",
            "role:admin",
        )
        assert cancelled["cancel_requested_count"] == 1
        with pytest.raises(ModelExecutionError) as captured:
            await running
        assert captured.value.code is ModelErrorCode.USER_CANCELLED

    asyncio.run(scenario())
    task = list_ollama_executions()[0]
    assert task["status"] == "cancelled"
    assert scheduler.released == [
        ("lease-cancel", "OLLAMA_EXECUTION_CANCELLED")
    ]
    close_connection()


def test_queue_timeout_and_restart_recovery_are_persistent(tmp_path, monkeypatch):
    provider, profile = setup_runtime(tmp_path, monkeypatch)
    scheduler = FakeScheduler(
        [FakeDecision(AdmissionStatus.QUEUED, reason="REMOTE_RUNTIME_BUSY")]
    )
    coordinator = OllamaExecutionCoordinator(
        scheduler=scheduler,
        transport=SequenceTransport(),
        runtime_probe=runtime_ready,
        queue_timeout_seconds=0.12,
        poll_interval_seconds=0.05,
    )
    with pytest.raises(ModelExecutionError) as timed_out:
        asyncio.run(
            coordinator.execute(provider, profile, model_request(), {})
        )
    assert timed_out.value.code is ModelErrorCode.TIMEOUT
    assert list_ollama_executions()[0]["status"] == "timed_out"

    now = "2026-07-30T00:00:00+00:00"
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        conn.execute(
            """INSERT INTO ollama_execution_tasks(
                   execution_id,task_id,owner_id,provider_id,model_profile_id,
                   runtime_id,model_name,request_hash,status,lease_id,
                   created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "interrupted-execution",
                "interrupted-task",
                "role:admin",
                provider["id"],
                profile["id"],
                "ollama:test-runtime",
                "writer:latest",
                "f" * 64,
                "running",
                "lease-interrupted",
                now,
                now,
            ),
        )
        conn.commit()
    scheduler.known_leases.append(
        {
            "id": "lease-interrupted",
            "owner_type": "aetherdb_task",
            "task_id": "interrupted-task",
        }
    )
    recovered = recover_interrupted_ollama_executions(scheduler)
    assert recovered["interrupted_count"] == 1
    assert get_ollama_execution("interrupted-execution")["status"] == "interrupted"
    assert scheduler.released[-1] == (
        "lease-interrupted",
        "OLLAMA_EXECUTION_INTERRUPTED",
    )
    close_connection()
