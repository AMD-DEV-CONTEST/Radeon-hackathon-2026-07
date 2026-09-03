from types import SimpleNamespace

import pytest

import autoflow.deepseek as model_provider
from autoflow.deepseek import DeepSeekInterpreter, PROVIDERS


class MemoryCredentials:
    def __init__(self):
        self.config = {}

    def get_config(self):
        return dict(self.config)

    def set_config(self, config):
        self.config = dict(config)

    def delete_config(self):
        self.config = {}


class FakeModels:
    def __init__(self, models=None, error=None):
        self.models = models or []
        self.error = error

    def list(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=[SimpleNamespace(id=item) for item in self.models])


class FakeOpenAI:
    models = ["deepseek-v4-pro", "deepseek-v4-flash"]
    error = None
    last_kwargs = None

    def __init__(self, **kwargs):
        FakeOpenAI.last_kwargs = kwargs
        self.models = FakeModels(FakeOpenAI.models, FakeOpenAI.error)


def test_deepseek_discovers_models_and_saves_only_safe_status(monkeypatch):
    monkeypatch.setattr(model_provider, "OpenAI", FakeOpenAI)
    FakeOpenAI.models = ["deepseek-v4-pro", "deepseek-v4-flash"]
    FakeOpenAI.error = None
    credentials = MemoryCredentials()
    interpreter = DeepSeekInterpreter(credentials=credentials)
    status = interpreter.configure_provider("deepseek", api_key="sk-test-key-123456789")

    assert status["model"] == "deepseek-v4-flash"
    assert status["configured"] is True
    assert "api_key" not in status
    assert credentials.config["api_key"].startswith("sk-")


def test_moonshot_china_uses_official_cn_endpoint(monkeypatch):
    monkeypatch.setattr(model_provider, "OpenAI", FakeOpenAI)
    FakeOpenAI.models = ["moonshot-v1-auto", "kimi-k3"]
    FakeOpenAI.error = None
    interpreter = DeepSeekInterpreter(credentials=MemoryCredentials())
    status = interpreter.configure_provider("moonshot_cn", api_key="sk-moonshot-test-12345", model="kimi-k3")

    assert status["provider"] == "moonshot_cn"
    assert status["model"] == "kimi-k3"
    assert FakeOpenAI.last_kwargs["base_url"] == "https://api.moonshot.cn/v1"


def test_custom_provider_allows_manual_model_when_models_endpoint_missing(monkeypatch):
    class MissingModelsError(Exception):
        status_code = 404

    monkeypatch.setattr(model_provider, "OpenAI", FakeOpenAI)
    FakeOpenAI.error = MissingModelsError()
    interpreter = DeepSeekInterpreter(credentials=MemoryCredentials())
    status = interpreter.configure_provider("custom", base_url="http://127.0.0.1:11434/v1", model="llama3.2")

    assert status["configured"] is True
    assert status["model"] == "llama3.2"
    assert status["requires_key"] is False


def test_provider_catalog_is_explicit_and_has_at_least_ten_choices():
    assert len(PROVIDERS) >= 10
    assert len({item["name"] for item in PROVIDERS.values()}) == len(PROVIDERS)
    for provider in PROVIDERS.values():
        assert provider["description"]
        assert provider["credential_hint"]
        assert provider["model_hint"]
        assert isinstance(provider["requires_key"], bool)
        assert isinstance(provider["manual_model"], bool)

    for provider_id in ("deepseek", "moonshot_cn", "moonshot_global", "openai", "siliconflow"):
        assert "API" not in PROVIDERS[provider_id]["description"]


def test_volcengine_accepts_explicit_endpoint_id_when_model_listing_is_missing(monkeypatch):
    class MissingModelsError(Exception):
        status_code = 404

    monkeypatch.setattr(model_provider, "OpenAI", FakeOpenAI)
    FakeOpenAI.error = MissingModelsError()
    interpreter = DeepSeekInterpreter(credentials=MemoryCredentials())
    status = interpreter.configure_provider(
        "volcengine_ark",
        api_key="ark-test-key-123456789",
        model="ep-20260804-example",
    )

    assert status["provider"] == "volcengine_ark"
    assert status["model"] == "ep-20260804-example"
    assert status["providers"][8]["manual_model"] is True
    assert "api_key" not in status


def test_builtin_provider_rejects_base_url_override():
    interpreter = DeepSeekInterpreter(credentials=MemoryCredentials())
    with pytest.raises(ValueError, match="内置模型服务商不允许修改接口地址"):
        interpreter.configure_provider(
            "deepseek",
            api_key="sk-test-key-123456789",
            base_url="https://attacker.example/v1",
        )


def test_remote_http_custom_provider_rejects_api_key():
    interpreter = DeepSeekInterpreter(credentials=MemoryCredentials())
    with pytest.raises(ValueError, match="必须使用 HTTPS"):
        interpreter.configure_provider(
            "custom",
            api_key="sk-test-key-123456789",
            base_url="http://models.example/v1",
            model="example-model",
        )
