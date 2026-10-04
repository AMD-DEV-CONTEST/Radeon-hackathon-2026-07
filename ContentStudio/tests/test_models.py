import httpx
import openai
import pytest
from content_studio.config import ProviderConfig
from content_studio.core.models import LLMClient, LLMError


def _provider():
    return ProviderConfig(name="deepseek", base_url="http://x", api_key="sk-x", model="m")


def _rate_limit_error(message: str = "boom") -> openai.RateLimitError:
    # openai>=1.x requires a real httpx.Response (it reads response.request/headers).
    request = httpx.Request("POST", "http://x")
    response = httpx.Response(status_code=429, request=request)
    return openai.RateLimitError(message, response=response, body=None)


class FakeMessage:
    def __init__(self, content): self.content = content

class FakeChoice:
    def __init__(self, content): self.message = FakeMessage(content)

class FakeResp:
    def __init__(self, content): self.choices = [FakeChoice(content)]

class FakeCompletions:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def create(self, **kw):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception): raise out
        return FakeResp(out)

class FakeChat:
    def __init__(self, completions): self.completions = completions
class FakeClient:
    def __init__(self, completions): self.chat = FakeChat(completions)


def test_complete_json_returns_content():
    comp = FakeCompletions(['{"a":1}'])
    c = LLMClient(_provider(), client=FakeClient(comp))
    assert c.complete_json("sys", "usr") == '{"a":1}'
    assert comp.calls == 1


def test_retry_on_rate_limit_then_success():
    comp = FakeCompletions([_rate_limit_error(), '{"a":1}'])
    c = LLMClient(_provider(), client=FakeClient(comp), sleeper=lambda _s: None)
    assert c.complete_json("sys", "usr") == '{"a":1}'
    assert comp.calls == 2


def test_retry_exhausted_raises_llm_error():
    err = _rate_limit_error()
    comp = FakeCompletions([err, err, err])
    c = LLMClient(_provider(), client=FakeClient(comp), sleeper=lambda _s: None)
    with pytest.raises(LLMError):
        c.complete_json("sys", "usr")
    assert comp.calls == 3


def test_non_retryable_error_wrapped_immediately():
    comp = FakeCompletions([ValueError("bad")])
    c = LLMClient(_provider(), client=FakeClient(comp))
    with pytest.raises(LLMError):
        c.complete_json("sys", "usr")
    assert comp.calls == 1


def test_vision_call_falls_back_to_text_when_unsupported(tmp_path):
    from PIL import Image
    img = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(img)

    class Comp:
        def __init__(self): self.calls = 0
        def create(self, **kw):
            self.calls += 1
            has_image = any(isinstance(m.get("content"), list) for m in kw.get("messages", []))
            if has_image:
                raise Exception("Error code: 400 - messages.content.type 非法取值范围 ['text']")
            return FakeResp('{"title":"T"}')

    comp = Comp()
    c = LLMClient(_provider(), client=FakeClient(comp), sleeper=lambda _s: None)
    out = c.complete_json("sys", "usr", images=[str(img)])
    assert out == '{"title":"T"}'
    assert comp.calls == 2   # 1 次视觉失败 + 1 次纯文本成功
