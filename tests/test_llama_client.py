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
    user_content = captured["body"]["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": "Describe visible evidence."}
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
