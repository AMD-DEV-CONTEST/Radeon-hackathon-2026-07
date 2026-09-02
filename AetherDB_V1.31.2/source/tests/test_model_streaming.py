import asyncio
import json

import pytest

import services.database_registry as registry
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from services.model_execution import ModelTaskRequest, ModelTaskResult
from services.model_reliability import ModelErrorCode, ModelExecutionError
from services.model_streaming import (
    StreamAccumulator,
    StreamSession,
    stream_model_task,
)
from tests.asgi_client import asgi_request


class FakeGateway:
    def __init__(self, content="final text", error=None):
        self.content = content
        self.error = error

    async def execute(self, request):
        if self.error:
            raise self.error
        return ModelTaskResult(
            task_id=request.task_id,
            model_profile_id="model-1",
            provider_id="provider-1",
            content=self.content,
            usage={"input_tokens": 2, "output_tokens": 3},
        )


def request():
    return ModelTaskRequest(
        task_id="stream-task",
        task_type="chapter_analysis",
        database_id="default",
        book_id="default",
        messages=({"role": "user", "content": "chapter"},),
    )


def collect(gateway):
    async def run():
        return [event async for event in stream_model_task(gateway, request())]

    return asyncio.run(run())


def test_stream_envelope_has_monotonic_sequence_and_final_boundary():
    model_text = '{"event":"task_done","sequence":999}'
    events = collect(FakeGateway(content=model_text))
    assert [event.sequence for event in events] == list(range(len(events)))
    assert [event.event for event in events] == [
        "task_started",
        "routing_resolved",
        "final_start",
        "final_delta",
        "final_end",
        "usage_update",
        "task_done",
    ]
    assert events[3].payload == {"delta": model_text}


def test_duplicate_and_out_of_order_events_do_not_repeat_content():
    events = collect(FakeGateway(content="abc"))
    accumulator = StreamAccumulator()
    final_delta = next(event for event in events if event.event == "final_delta")
    assert accumulator.apply(final_delta) is True
    assert accumulator.apply(final_delta) is False
    older = final_delta.model_copy(update={"sequence": final_delta.sequence - 1})
    assert accumulator.apply(older) is False
    assert accumulator.final_content == "abc"


def test_stream_error_uses_standard_code_without_raw_exception():
    events = collect(
        FakeGateway(error=ModelExecutionError(ModelErrorCode.AUTH_FAILED, "sensitive provider detail"))
    )
    assert events[-1].event == "stream_error"
    assert events[-1].payload == {
        "error_code": "AUTH_FAILED",
        "partial_final_available": False,
    }
    assert "sensitive provider detail" not in json.dumps(events[-1].model_dump())


def test_partial_final_can_be_kept_or_discarded_after_interruption():
    keep_session = StreamSession("keep")
    keep_session.append_delta("final", "partial")
    assert keep_session.partial_final(keep=True) == "partial"

    discard_session = StreamSession("discard")
    discard_session.append_delta("final", "partial")
    assert discard_session.partial_final(keep=False) == ""
    assert discard_session.final_content == ""


def test_stream_cancellation_and_output_limit_are_explicit():
    events = collect(FakeGateway(error=asyncio.CancelledError()))
    assert events[-1].event == "task_cancelled"

    session = StreamSession("limited", max_output_chars=3)
    with pytest.raises(ModelExecutionError) as captured:
        session.append_delta("final", "four")
    assert captured.value.code is ModelErrorCode.STREAM_INTERRUPTED


def test_thinking_closes_before_final_and_cannot_resume_after_final():
    result = ModelTaskResult(
        task_id="stream-task",
        model_profile_id="model-1",
        provider_id="provider-1",
        provider_model_name="writer-v1",
        thinking_content="private reasoning summary",
        content="answer",
        finish_reason="stop",
    )

    class ThinkingGateway:
        async def execute(self, request):
            return result

    events = collect(ThinkingGateway())
    names = [event.event for event in events]
    assert names.index("thinking_end") < names.index("final_start")
    assert all(event.protocol_version == "1.0" for event in events)
    assert next(event for event in events if event.event == "final_end").payload["provider_model_name"] == "writer-v1"

    session = StreamSession("locked")
    session.append_delta("final", "started")
    with pytest.raises(ModelExecutionError):
        session.append_delta("thinking", "too late")


def test_stream_final_boundary_exposes_warnings_and_truncation():
    result = ModelTaskResult(
        task_id="stream-task",
        model_profile_id="model-1",
        provider_id="provider-1",
        content="partial answer",
        finish_reason="length",
        warnings=("OUTPUT_TRUNCATED", "TOOL_CALLS_IGNORED"),
    )

    class TruncatedGateway:
        async def execute(self, request):
            return result

    events = collect(TruncatedGateway())
    final_end = next(event for event in events if event.event == "final_end")
    assert final_end.payload["truncated"] is True
    assert final_end.payload["warnings"] == ["OUTPUT_TRUNCATED", "TOOL_CALLS_IGNORED"]


def test_ndjson_endpoint_is_admin_only_and_wraps_output(tmp_path, monkeypatch):
    from api import model_execution as execution_api

    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()
    app.dependency_overrides[execution_api.get_execution_gateway] = lambda: FakeGateway("endpoint output")
    payload = {
        "task_id": "endpoint-task",
        "task_type": "chapter_analysis",
        "database_id": "default",
        "book_id": "default",
        "messages": [{"role": "user", "content": "chapter"}],
    }
    try:
        assert asgi_request(app, "POST", "/api/model-routing/execute-stream", json_body=payload)[0] == 401
        status, body = asgi_request(
            app,
            "POST",
            "/api/model-routing/execute-stream",
            headers={"X-API-Key": ADMIN_API_KEY},
            json_body=payload,
        )
    finally:
        app.dependency_overrides.clear()
    assert status == 200
    lines = [json.loads(line) for line in body.splitlines()]
    assert lines[-1]["event"] == "task_done"
    assert lines[2]["event"] == "final_start"
    assert lines[3]["payload"]["delta"] == "endpoint output"
    close_connection()
