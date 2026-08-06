import json
from pathlib import Path

import httpx
import pytest

from xianglens.config import PROJECT_ROOT
from xianglens.inference.llama_client import LlamaCppClient


@pytest.mark.asyncio
async def test_multimodal_request_matches_openai_compatible_contract() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "visible_elements": ["test subject"],
                                    "composition": "centered",
                                    "text_candidates": [],
                                    "privacy_candidates": [],
                                    "uncertainties": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = LlamaCppClient(
        base_url="https://radeon.example.test/v1",
        api_key="secret",
        model="test-model",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )
    image_path: Path = next((PROJECT_ROOT / "data/fixtures/images").glob("*.jpg"))
    result = await client.inspect_image(image_path, "Describe visible evidence.")

    assert result["composition"] == "centered"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": True}
    assert captured["body"]["reasoning_budget"] == 1024
    assert captured["body"]["max_tokens"] == 2224
    user_content = captured["body"]["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": "Describe visible evidence."}
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_reasoning_budget_exhaustion_retries_with_expanded_budget() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 2:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"status":"recovered"}'}}]},
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "internal reasoning is intentionally not exposed",
                        }
                    }
                ]
            },
        )

    client = LlamaCppClient(
        base_url="https://radeon.example.test/v1",
        api_key="",
        model="test-model",
        timeout_seconds=30,
        reasoning_budget=512,
        transport=httpx.MockTransport(handler),
    )
    result = await client.chat([{"role": "user", "content": "Return JSON."}], max_tokens=10)

    assert result == '{"status":"recovered"}'
    assert len(payloads) == 2
    assert payloads[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert payloads[0]["reasoning_budget"] == 512
    assert payloads[0]["max_tokens"] == 522
    assert payloads[1]["chat_template_kwargs"] == {"enable_thinking": True}
    assert payloads[1]["reasoning_budget"] == 1024
    assert payloads[1]["max_tokens"] == 1034


@pytest.mark.asyncio
async def test_expanded_reasoning_exhaustion_has_a_final_no_thinking_fallback() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 3:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"status":"fallback"}'}}]},
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "reasoning without final content",
                        }
                    }
                ]
            },
        )

    client = LlamaCppClient(
        base_url="https://radeon.example.test/v1",
        api_key="",
        model="test-model",
        timeout_seconds=30,
        reasoning_budget=1024,
        transport=httpx.MockTransport(handler),
    )
    result = await client.chat([{"role": "user", "content": "Return JSON."}], max_tokens=10)

    assert result == '{"status":"fallback"}'
    assert len(payloads) == 3
    assert payloads[0]["reasoning_budget"] == 1024
    assert payloads[1]["reasoning_budget"] == 2048
    assert payloads[2]["chat_template_kwargs"] == {"enable_thinking": False}
    assert payloads[2]["reasoning_budget"] == 0
    assert payloads[2]["max_tokens"] == 10
