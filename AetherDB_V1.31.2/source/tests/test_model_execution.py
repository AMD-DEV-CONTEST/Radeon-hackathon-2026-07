import asyncio

from services.model_execution import (
    LegacyLLMCompatibilityGateway,
    ModelTaskRequest,
    execute_sync,
    sanitize_client_metadata,
    normalize_provider_response,
)
from services.world_import.interfaces import LLMChapterAnalyzer


def make_request():
    return ModelTaskRequest(
        task_id="task-1",
        task_type="chapter_analysis",
        database_id="database-1",
        book_id="book-1",
        messages=({"role": "user", "content": "analyze"},),
        requires_json=True,
        requires_streaming=False,
    )


class FakeLegacyRouter:
    def __init__(self):
        self.calls = []

    def route(self, task_type, messages, **kwargs):
        self.calls.append((task_type, messages, kwargs))
        return '{"entities": [], "relations": []}'


class FakeGateway:
    def __init__(self):
        self.requests = []

    async def execute(self, request):
        from services.model_execution import ModelTaskResult

        self.requests.append(request)
        return ModelTaskResult(
            task_id=request.task_id,
            model_profile_id="test-model",
            provider_id="test-provider",
            content='{"entities": [], "relations": []}',
        )

    async def stream(self, request):
        yield {"type": "done", "task_id": request.task_id}


def test_legacy_gateway_preserves_router_call_shape():
    router = FakeLegacyRouter()
    result = asyncio.run(LegacyLLMCompatibilityGateway(router).execute(make_request()))

    assert result.content == '{"entities": [], "relations": []}'
    assert result.provider_id == "legacy_router"
    assert result.model_profile_id == "legacy_default"
    assert result.provider_model_name == "legacy_default"
    assert router.calls == [
        (
            "chapter_analysis",
            [{"role": "user", "content": "analyze"}],
            {},
        )
    ]


def test_provider_response_normalizes_usage_and_reasoning_fields():
    result = normalize_provider_response({
        "content": "answer",
        "reasoning_content": "summary",
        "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        "finish_reason": "stop",
        "provider_request_id": "request-id",
    })

    assert result.content == "answer"
    assert result.thinking_content == "summary"
    assert result.usage == {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}
    assert result.finish_reason == "stop"


def test_unknown_usage_remains_unknown_instead_of_becoming_zero():
    result = normalize_provider_response({"content": "answer"})

    assert result.usage == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_openai_shape_keeps_only_final_text_and_reports_truncation():
    result = normalize_provider_response({
        "id": "response-1",
        "choices": [{
            "message": {
                "content": "partial answer",
                "reasoning_content": "short summary",
                "tool_calls": [{"id": "call-1"}],
                "plan": "must not enter final output",
            },
            "finish_reason": "length",
        }],
        "usage": {"prompt_tokens": 7},
    })

    assert result.content == "partial answer"
    assert "must not enter final output" not in result.content
    assert result.thinking_content == "short summary"
    assert result.usage == {"input_tokens": 7, "output_tokens": None, "total_tokens": None}
    assert result.finish_reason == "length"
    assert result.provider_request_id == "response-1"
    assert result.warnings == ("OUTPUT_TRUNCATED", "TOOL_CALLS_IGNORED", "NON_FINAL_PROVIDER_FIELDS_IGNORED")


def test_ollama_shape_normalizes_message_and_native_usage_counts():
    result = normalize_provider_response({
        "message": {"role": "assistant", "content": "local answer", "thinking": "summary"},
        "prompt_eval_count": 11,
        "eval_count": 13,
        "done_reason": "stop",
    })

    assert result.content == "local answer"
    assert result.thinking_content == "summary"
    assert result.usage == {"input_tokens": 11, "output_tokens": 13, "total_tokens": 24}
    assert result.warnings == ()


def test_legacy_gateway_stream_has_final_and_done_events():
    async def collect():
        gateway = LegacyLLMCompatibilityGateway(FakeLegacyRouter())
        return [event async for event in gateway.stream(make_request())]

    assert asyncio.run(collect()) == [
        {"type": "final", "content": '{"entities": [], "relations": []}'},
        {"type": "done", "task_id": "task-1"},
    ]


def test_client_metadata_cannot_set_privileged_routing_fields():
    assert sanitize_client_metadata(
        {
            "ui_source": "chapter_editor",
            "provider_id": "forbidden-provider",
            "fallback_policy": "always",
            "privacy_level": "public",
        }
    ) == {"ui_source": "chapter_editor"}


def test_chapter_analyzer_uses_injected_gateway(monkeypatch):
    monkeypatch.setattr(
        "services.prompt_engine.composer.PromptComposer.compose",
        lambda self, task_type, variables=None, profile_id=None: "chapter prompt",
    )
    monkeypatch.setattr(
        "services.database_registry.get_active_database_id",
        lambda: "database-1",
    )
    monkeypatch.setattr(
        "services.database_registry.get_active_book_id",
        lambda: "book-1",
    )
    gateway = FakeGateway()

    result = LLMChapterAnalyzer(gateway=gateway).analyze("chapter text", chapter_index=3)

    assert result["entities"] == []
    assert result["relations"] == []
    assert result["raw_response"] == '{"entities": [], "relations": []}'
    assert len(gateway.requests) == 1
    request = gateway.requests[0]
    assert request.task_type == "chapter_analysis"
    assert request.database_id == "database-1"
    assert request.book_id == "book-1"
    assert request.requires_json is True
    assert request.metadata == {"chapter_index": 3}


def test_execute_sync_works_inside_an_existing_event_loop():
    async def run():
        return execute_sync(FakeGateway(), make_request())

    result = asyncio.run(run())
    assert result.content == '{"entities": [], "relations": []}'
