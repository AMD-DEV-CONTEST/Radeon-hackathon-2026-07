from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from colorgraph.agent.creative_provider import (
    CreativeModelRequest,
    CreativeProviderRuntime,
    CreativeRole,
    FakeCreativeModelProvider,
    FallbackDecision,
    OllamaResponsesProvider,
    OpenAIResponsesProvider,
    ProviderAudio,
    ProviderBoundary,
    ProviderCapabilities,
    ProviderError,
    ProviderFailureType,
    ProviderImage,
    ProviderResponseCache,
    ProviderUsage,
    RawProviderResponse,
    RuntimeBudget,
    RuntimePolicy,
    response_cache_key,
    strict_output_schema,
)


class ExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    result: str
    score: float | None = None


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _request(
    *,
    role: CreativeRole = CreativeRole.DIRECTOR,
    images: tuple[ProviderImage, ...] = (),
    audio: tuple[ProviderAudio, ...] = (),
    consent: bool = False,
    prompt: str = "Interpret only the supplied evidence and return the requested schema.",
    estimated_input_tokens: int = 0,
    request_id: str | None = None,
) -> CreativeModelRequest[ExampleOutput]:
    return CreativeModelRequest(
        role=role,
        prompt=prompt,
        prompt_version="director/v1",
        schema_version="example/v1",
        output_model=ExampleOutput,
        input_asset_digests=(_sha(b"frozen-context"),),
        images=images,
        audio=audio,
        max_output_tokens=64,
        estimated_input_tokens=estimated_input_tokens,
        cloud_upload_consent=consent,
        request_id=request_id,
    )


def _providers(provider: FakeCreativeModelProvider | OpenAIResponsesProvider):
    return {role: provider for role in CreativeRole}


def _explicit_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        image_input=True,
        strict_structured_output=True,
        maximum_context_tokens=128_000,
        maximum_images=32,
        batch_requests=False,
    )


def _success(*, result: str = "grounded") -> RawProviderResponse:
    return RawProviderResponse(
        text=json.dumps({"result": result, "score": 0.8}),
        usage=ProviderUsage(
            input_tokens=12,
            output_tokens=8,
            total_tokens=20,
            estimated_cost_usd=0.01,
        ),
        response_id="response:test",
    )


async def test_success_uses_role_route_strict_schema_and_content_cache(tmp_path) -> None:
    director = FakeCreativeModelProvider(responses=[_success()], provider_id="director-provider")
    strategist = FakeCreativeModelProvider(
        responses=[_success(result="strategy")],
        provider_id="strategist-provider",
    )
    critic = FakeCreativeModelProvider(
        responses=[_success(result="critique")],
        provider_id="critic-provider",
    )
    cache = ProviderResponseCache(tmp_path / "provider-cache")
    runtime = CreativeProviderRuntime(
        {
            CreativeRole.DIRECTOR: director,
            CreativeRole.STRATEGIST: strategist,
            CreativeRole.CRITIC: critic,
        },
        policy=RuntimePolicy(maximum_retries=0),
        cache=cache,
    )

    first = await runtime.run(_request(request_id="request:first"))
    second = await runtime.run(_request(request_id="request:cached"))

    assert first.output.result == "grounded"
    assert first.audit.provider_id == "director-provider"
    assert first.audit.request_id == "request:first"
    assert second.audit.request_id == "request:cached"
    assert first.audit.structured_response == {"result": "grounded", "score": 0.8}
    assert second.audit.cache_hit is True
    assert director.calls == 1
    schema = director.schemas[0]
    assert schema["required"] == ["result", "score"]
    assert schema["additionalProperties"] is False
    key = response_cache_key(_request(), director)
    assert (tmp_path / "provider-cache" / f"{key}.json").is_file()
    assert response_cache_key(
        replace(_request(), max_output_tokens=65),
        director,
    ) != key


async def test_timeout_is_bounded_and_audited() -> None:
    async def delayed() -> RawProviderResponse:
        await asyncio.sleep(1)
        return _success()

    provider = FakeCreativeModelProvider(responses=[delayed])
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(timeout_seconds=0.01, maximum_retries=0),
    )

    with pytest.raises(ProviderError) as raised:
        await runtime.run(_request())

    assert raised.value.failure_type == ProviderFailureType.TIMEOUT
    assert runtime.audit_records[-1].failure_type == ProviderFailureType.TIMEOUT
    assert runtime.audit_records[-1].attempt_count == 1


async def test_429_retries_once_then_succeeds() -> None:
    provider = FakeCreativeModelProvider(
        responses=[
            ProviderError(
                ProviderFailureType.RATE_LIMITED,
                "HTTP 429",
                retryable=True,
                retry_after_seconds=0,
                status_code=429,
            ),
            _success(),
        ]
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(maximum_retries=1, retry_base_seconds=0),
    )

    result = await runtime.run(_request())

    assert result.output.result == "grounded"
    assert provider.calls == 2
    assert result.audit.attempt_count == 2


async def test_cancellation_propagates_and_is_audited() -> None:
    entered = asyncio.Event()

    async def blocked() -> RawProviderResponse:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    provider = FakeCreativeModelProvider(responses=[blocked])
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(timeout_seconds=5, maximum_retries=0),
    )
    task = asyncio.create_task(runtime.run(_request()))
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert runtime.audit_records[-1].failure_type == ProviderFailureType.CANCELLED
    assert runtime.audit_records[-1].success is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (RawProviderResponse(text="{"), ProviderFailureType.BAD_JSON),
        (
            RawProviderResponse(text=None, refusal="policy refusal"),
            ProviderFailureType.REFUSAL,
        ),
        (
            RawProviderResponse(
                text='{"result":"x","score":0.2}',
                incomplete_reason="max_output_tokens",
            ),
            ProviderFailureType.INCOMPLETE,
        ),
        (
            RawProviderResponse(text='{"result":"x","score":"high"}'),
            ProviderFailureType.SCHEMA_INVALID,
        ),
    ],
)
async def test_invalid_responses_fail_closed(
    raw: RawProviderResponse,
    expected: ProviderFailureType,
) -> None:
    provider = FakeCreativeModelProvider(responses=[raw])
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(maximum_retries=0),
    )

    with pytest.raises(ProviderError) as raised:
        await runtime.run(_request())

    assert raised.value.failure_type == expected
    assert runtime.audit_records[-1].structured_response is None


async def test_budget_aborts_before_provider_call_and_routes_to_explainable_fallback() -> None:
    provider = FakeCreativeModelProvider(responses=[_success()])
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(maximum_retries=0),
        budget=RuntimeBudget(
            maximum_provider_attempts=0,
            maximum_input_tokens=100,
            maximum_output_tokens=100,
            maximum_cost_usd=1,
        ),
    )

    result = await runtime.run_or_fallback(_request())

    assert isinstance(result, FallbackDecision)
    assert result.route == "local-clip-rule-planner"
    assert result.reason == ProviderFailureType.BUDGET_EXHAUSTED
    assert provider.calls == 0


async def test_offline_mode_never_calls_cloud_provider() -> None:
    provider = FakeCreativeModelProvider(
        responses=[_success()],
        boundary=ProviderBoundary.OPENAI,
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(
            network_enabled=False,
            cloud_provider_enabled=False,
            maximum_retries=0,
        ),
    )

    result = await runtime.run_or_fallback(_request())

    assert isinstance(result, FallbackDecision)
    assert result.reason == ProviderFailureType.OFFLINE
    assert provider.calls == 0


async def test_cloud_images_require_explicit_upload_consent() -> None:
    content = b"not-a-real-image-but-sufficient-for-wire-contract"
    image = ProviderImage(
        asset_id="frame:1",
        sha256=_sha(content),
        media_type="image/jpeg",
        content=content,
    )
    provider = FakeCreativeModelProvider(
        responses=[_success()],
        boundary=ProviderBoundary.OPENAI,
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(
            network_enabled=True,
            cloud_provider_enabled=True,
            maximum_retries=0,
        ),
    )

    with pytest.raises(ProviderError) as raised:
        await runtime.run(_request(images=(image,)))

    assert raised.value.failure_type == ProviderFailureType.CLOUD_CONSENT_REQUIRED
    assert provider.calls == 0


async def test_audio_capability_context_window_and_cloud_consent_are_enforced() -> None:
    content = b"short-audio-evidence"
    audio = ProviderAudio(
        asset_id="audio:scene-1",
        sha256=_sha(content),
        media_type="audio/wav",
        duration_seconds=2.5,
        content=content,
    )
    provider = FakeCreativeModelProvider(
        responses=[_success()],
        boundary=ProviderBoundary.OPENAI_COMPATIBLE,
        capabilities=ProviderCapabilities(
            image_input=True,
            audio_input=True,
            strict_structured_output=True,
            maximum_context_tokens=100,
            maximum_images=4,
            maximum_audio_seconds=3,
            batch_requests=False,
        ),
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(
            network_enabled=True,
            cloud_provider_enabled=True,
            maximum_retries=0,
        ),
    )

    without_consent = await runtime.run_or_fallback(_request(audio=(audio,)))
    over_context = await runtime.run_or_fallback(
        _request(audio=(audio,), consent=True, estimated_input_tokens=40)
    )
    accepted = await runtime.run(
        _request(audio=(audio,), consent=True, estimated_input_tokens=20)
    )

    assert isinstance(without_consent, FallbackDecision)
    assert without_consent.reason == ProviderFailureType.CLOUD_CONSENT_REQUIRED
    assert isinstance(over_context, FallbackDecision)
    assert over_context.reason == ProviderFailureType.CAPABILITY_MISMATCH
    assert accepted.output.result == "grounded"
    assert provider.calls == 1


async def test_corrupt_cache_fails_closed_and_is_audited(tmp_path) -> None:
    provider = FakeCreativeModelProvider(responses=[_success()])
    cache = ProviderResponseCache(tmp_path)
    request = _request()
    key = response_cache_key(request, provider)
    (tmp_path / f"{key}.json").write_text("{", encoding="utf-8")
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(maximum_retries=0),
        cache=cache,
    )

    result = await runtime.run_or_fallback(request)

    assert isinstance(result, FallbackDecision)
    assert result.reason == ProviderFailureType.INTERNAL
    assert provider.calls == 0
    assert runtime.audit_records[-1].failure_type == ProviderFailureType.INTERNAL
    assert runtime.audit_records[-1].attempt_count == 0


async def test_provider_failures_open_circuit_without_calling_provider_again() -> None:
    unavailable = ProviderError(
        ProviderFailureType.PROVIDER_UNAVAILABLE,
        "temporary provider failure",
        retryable=True,
        status_code=503,
    )
    provider = FakeCreativeModelProvider(responses=[unavailable, unavailable])
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(
            maximum_retries=0,
            circuit_failure_threshold=2,
            circuit_cooldown_seconds=60,
        ),
    )

    first = await runtime.run_or_fallback(_request(prompt="first frozen request"))
    second = await runtime.run_or_fallback(_request(prompt="second frozen request"))
    third = await runtime.run_or_fallback(_request(prompt="third frozen request"))

    assert isinstance(first, FallbackDecision)
    assert isinstance(second, FallbackDecision)
    assert isinstance(third, FallbackDecision)
    assert first.reason == ProviderFailureType.PROVIDER_UNAVAILABLE
    assert second.reason == ProviderFailureType.PROVIDER_UNAVAILABLE
    assert third.reason == ProviderFailureType.CIRCUIT_OPEN
    assert provider.calls == 2


async def test_shadow_replay_uses_bounded_concurrency_and_preserves_order() -> None:
    entered = 0
    both_entered = asyncio.Event()
    release = asyncio.Event()

    def response(result: str):
        async def wait_for_peer() -> RawProviderResponse:
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()
            return _success(result=result)

        return wait_for_peer

    provider = FakeCreativeModelProvider(
        responses=[response("first"), response("second")]
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(maximum_concurrency=2, maximum_retries=0),
    )
    replay = asyncio.create_task(
        runtime.shadow_replay(
            [
                _request(prompt="first frozen request"),
                _request(prompt="second frozen request"),
            ]
        )
    )
    await asyncio.wait_for(both_entered.wait(), timeout=0.5)
    release.set()
    results = await replay

    assert [result.output.result for result in results] == ["first", "second"]
    assert provider.calls == 2


async def test_openai_responses_adapter_sends_image_and_strict_schema_without_logging_secret(
) -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_shadow",
                "model": "configured-model-revision",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"result":"shadow","score":0.7}',
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            },
        )

    secret = "test-secret-must-not-enter-audit"
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIResponsesProvider(
        model_id="explicitly-configured-model",
        model_revision="configured",
        api_key_getter=lambda: secret,
        enabled=True,
        capabilities=_explicit_capabilities(),
        input_cost_per_million_tokens=2,
        output_cost_per_million_tokens=8,
        client=client,
    )
    runtime = CreativeProviderRuntime(
        _providers(provider),
        policy=RuntimePolicy(
            network_enabled=True,
            cloud_provider_enabled=True,
            maximum_retries=0,
        ),
    )
    content = b"representative-frame"
    image = ProviderImage(
        asset_id="frame:shadow",
        sha256=_sha(content),
        media_type="image/png",
        content=content,
    )

    result = await runtime.run(_request(images=(image,), consent=True))
    await client.aclose()

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["store"] is False
    assert payload["model"] == "explicitly-configured-model"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["input"][0]["content"][1]["type"] == "input_image"
    assert payload["input"][0]["content"][1]["image_url"].startswith(
        "data:image/png;base64,"
    )
    assert captured["authorization"] == f"Bearer {secret}"
    assert secret not in result.audit.model_dump_json()
    assert result.audit.boundary == ProviderBoundary.OPENAI
    assert result.audit.usage.estimated_cost_usd == pytest.approx(0.00012)


def test_openai_compatible_endpoint_reports_compatibility_not_equivalence() -> None:
    provider = OpenAIResponsesProvider(
        model_id="vendor-model",
        model_revision="vendor-revision",
        api_key_getter=lambda: "unused",
        enabled=False,
        base_url="https://models.example.test/v1",
        capabilities=_explicit_capabilities(),
        input_cost_per_million_tokens=0,
        output_cost_per_million_tokens=0,
    )

    assert provider.boundary == ProviderBoundary.OPENAI_COMPATIBLE
    assert provider.provider_id == "openai-responses"


async def test_ollama_provider_uses_native_generate_without_thinking_and_pins_identity(
    tmp_path,
) -> None:
    model_digest = "6" * 64
    calls: list[str] = []
    response_payload: dict[str, object] = {}
    loaded = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal loaded
        calls.append(request.url.path)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.20.6"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3.5:9b",
                            "digest": model_digest,
                            "details": {"quantization_level": "Q4_K_M"},
                        }
                    ]
                },
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "capabilities": ["completion", "vision", "tools"],
                    "details": {"quantization_level": "Q4_K_M"},
                    "model_info": {"qwen35.context_length": 262_144},
                },
            )
        if request.url.path == "/api/generate":
            generate_payload = json.loads(request.content)
            if generate_payload.get("keep_alive") == 0:
                loaded = False
                return httpx.Response(200, json={"done": True})
            response_payload.update(generate_payload)
            loaded = True
            return httpx.Response(
                200,
                json={
                    "model": "qwen3.5:9b",
                    "created_at": "2026-07-30T09:00:00Z",
                    "response": json.dumps(
                        {"result": "local", "score": 0.8}
                    ),
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 12,
                    "eval_count": 8,
                },
            )
        if request.url.path == "/api/ps":
            return httpx.Response(
                200,
                json={
                    "models": (
                        [
                            {
                                "name": "qwen3.5:9b",
                                "digest": model_digest,
                                "context_length": 262_144,
                                "size": 6_600_000_000,
                                "size_vram": 6_600_000_000,
                            }
                        ]
                        if loaded
                        else []
                    )
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OllamaResponsesProvider(
        model_id="qwen3.5:9b",
        expected_model_digest=model_digest,
        expected_runtime_version="0.20.6",
        enabled=True,
        capabilities=ProviderCapabilities(
            image_input=True,
            strict_structured_output=True,
            maximum_context_tokens=262_144,
            maximum_images=18,
            batch_requests=False,
        ),
        client=client,
    )
    image_content = b"local-frame"
    image = ProviderImage(
        asset_id="frame:local",
        sha256=_sha(image_content),
        media_type="image/jpeg",
        content=image_content,
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            network_enabled=False,
            cloud_provider_enabled=False,
            maximum_retries=0,
        ),
        cache=ProviderResponseCache(tmp_path / "cache"),
    )

    result = await runtime.run(_request(images=(image,), consent=False))
    await runtime.release()
    await client.aclose()

    assert provider.boundary == ProviderBoundary.LOCAL
    assert provider.provider_id == "ollama-generate-structural-local"
    assert result.output.result == "local"
    assert result.audit.response_id is not None
    assert result.audit.response_id.startswith("ollama_local_")
    assert len(result.audit.response_id) == 37
    assert result.audit.model_revision == (
        f"ollama-0.20.6/sha256:{model_digest}"
    )
    assert result.audit.hardware_evidence is not None
    assert result.audit.hardware_evidence.quantization_level == "Q4_K_M"
    assert result.audit.hardware_evidence.gpu_verified
    assert result.audit.hardware_evidence.gpu_offload_ratio == 1
    assert result.audit.hardware_evidence.vram_release_verified
    assert response_payload["model"] == "qwen3.5:9b"
    assert response_payload["stream"] is False
    assert response_payload["think"] is False
    assert response_payload["options"] == {
        "num_ctx": 262_144,
        "num_predict": 64,
        "seed": 0,
        "temperature": 0,
    }
    assert response_payload["images"] == [
        base64.b64encode(image_content).decode("ascii")
    ]
    assert response_payload["prompt"] == (
        "Interpret only the supplied evidence and return the requested schema."
    )
    assert "title" not in json.dumps(response_payload["format"])
    assert result.audit.usage == ProviderUsage(
        input_tokens=12,
        output_tokens=8,
        total_tokens=20,
        estimated_cost_usd=0,
    )
    assert calls == [
        "/api/version",
        "/api/tags",
        "/api/show",
        "/api/generate",
        "/api/ps",
        "/api/generate",
        "/api/ps",
        "/api/generate",
        "/api/ps",
    ]


async def test_ollama_unload_waits_for_asynchronous_runner_removal() -> None:
    process_checks = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal process_checks
        if request.url.path == "/api/generate":
            assert json.loads(request.content) == {
                "model": "qwen3.5:9b",
                "keep_alive": 0,
            }
            return httpx.Response(200, json={"done": True})
        if request.url.path == "/api/ps":
            process_checks += 1
            return httpx.Response(
                200,
                json={
                    "models": (
                        [{"name": "qwen3.5:9b"}]
                        if process_checks == 1
                        else []
                    )
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OllamaResponsesProvider(
        model_id="qwen3.5:9b",
        expected_model_digest="6" * 64,
        expected_runtime_version="0.20.6",
        enabled=True,
        capabilities=_explicit_capabilities(),
        client=client,
    )

    await provider._unload(client)
    await client.aclose()

    assert process_checks == 2


async def test_ollama_provider_digest_mismatch_fails_before_generation(
    tmp_path,
) -> None:
    generation_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal generation_called
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.20.6"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3.5:9b",
                            "digest": "7" * 64,
                        }
                    ]
                },
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "capabilities": ["completion", "vision"],
                    "model_info": {"qwen35.context_length": 262_144},
                },
            )
        generation_called = True
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OllamaResponsesProvider(
        model_id="qwen3.5:9b",
        expected_model_digest="6" * 64,
        expected_runtime_version="0.20.6",
        enabled=True,
        capabilities=ProviderCapabilities(
            image_input=True,
            strict_structured_output=True,
            maximum_context_tokens=262_144,
            maximum_images=18,
            batch_requests=False,
        ),
        client=client,
    )
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(maximum_retries=0),
        cache=ProviderResponseCache(tmp_path / "cache"),
    )

    result = await runtime.run_or_fallback(_request())
    await client.aclose()

    assert isinstance(result, FallbackDecision)
    assert result.reason == ProviderFailureType.CAPABILITY_MISMATCH
    assert not generation_called


async def test_ollama_provider_rejects_cpu_only_process_report() -> None:
    model_digest = "7" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.20.6"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3.5:9b",
                            "digest": model_digest,
                            "details": {"quantization_level": "Q4_K_M"},
                        }
                    ]
                },
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "capabilities": ["completion", "vision"],
                    "details": {"quantization_level": "Q4_K_M"},
                    "model_info": {"qwen35.context_length": 32_768},
                },
            )
        if request.url.path == "/api/generate":
            return httpx.Response(
                200,
                json={
                    "response": json.dumps({"result": "cpu"}),
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 4,
                    "eval_count": 2,
                },
            )
        if request.url.path == "/api/ps":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3.5:9b",
                            "digest": model_digest,
                            "context_length": 32_768,
                            "size": 6_600_000_000,
                            "size_vram": 0,
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OllamaResponsesProvider(
        model_id="qwen3.5:9b",
        expected_model_digest=model_digest,
        expected_runtime_version="0.20.6",
        enabled=True,
        capabilities=ProviderCapabilities(
            image_input=True,
            strict_structured_output=True,
            maximum_context_tokens=32_768,
            maximum_images=18,
            batch_requests=False,
        ),
        client=client,
    )

    with pytest.raises(ProviderError, match="sufficiently resident") as error:
        await provider.generate(
            _request(),
            strict_schema=strict_output_schema(ExampleOutput),
        )
    await client.aclose()

    assert error.value.failure_type == ProviderFailureType.CAPABILITY_MISMATCH


def test_ollama_provider_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaResponsesProvider(
            model_id="qwen3.5:9b",
            expected_model_digest="6" * 64,
            expected_runtime_version="0.20.6",
            enabled=True,
            base_url="https://models.example.test/v1",
            capabilities=_explicit_capabilities(),
        )


def test_schema_normalizer_requires_optional_nullable_fields() -> None:
    schema = strict_output_schema(ExampleOutput)

    assert schema["required"] == ["result", "score"]
    assert schema["additionalProperties"] is False
    assert "default" not in json.dumps(schema)
