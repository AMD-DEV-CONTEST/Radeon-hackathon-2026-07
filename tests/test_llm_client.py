import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm.client import LLMClient, LLMClientError


class StructuredReply(BaseModel):
    answer: str


def make_transport(contents: list[str]) -> tuple[httpx.MockTransport, list[dict[str, object]]]:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = contents.pop(0)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler), requests


def test_generate_text_uses_configured_openai_endpoint() -> None:
    transport, requests = make_transport(["service ready"])
    client = LLMClient(Settings(), transport=transport)

    assert asyncio.run(client.generate_text("Say hello")) == "service ready"
    assert requests[0]["model"] == "qwen3.6-office-agent"
    assert requests[0]["messages"][-1]["content"] == "Say hello"
    assert requests[0]["max_tokens"] == 384


def test_generate_json_retries_once_after_invalid_output() -> None:
    transport, requests = make_transport(["not json", '{"answer":"verified"}'])
    client = LLMClient(Settings(), transport=transport)

    result = asyncio.run(client.generate_json(StructuredReply, "Return a result"))
    assert result.answer == "verified"
    assert len(requests) == 2


def test_generate_text_reports_http_errors() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(503, text="offline"))
    client = LLMClient(Settings(), transport=transport)

    with pytest.raises(LLMClientError, match="model generation failed"):
        asyncio.run(client.generate_text("Say hello"))
