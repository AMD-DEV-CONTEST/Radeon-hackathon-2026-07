import json

import radeon_sentinel.model as model_module
from radeon_sentinel.model import OpenAICompatibleModelClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": "local response"}}]}
        ).encode("utf-8")


def test_openai_compatible_client_builds_expected_request(
    monkeypatch,
) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(model_module, "urlopen", fake_urlopen)
    client = OpenAICompatibleModelClient(
        base_url="https://radeon.example/v1",
        model="qwen",
        api_key="test-only-key",
        timeout_seconds=7,
    )

    result = client.generate([{"role": "user", "content": "hello"}])

    assert result == "local response"
    assert captured == {
        "url": "https://radeon.example/v1/chat/completions",
        "authorization": "Bearer test-only-key",
        "payload": {
            "model": "qwen",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.1,
        },
        "timeout": 7,
    }
