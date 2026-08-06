"""LLM Provider — abstract interface for all LLM backends.

V1.24 Architecture: providers are internal, not user-facing plugins.
Supports: OpenAI-compatible, Ollama, Claude (Anthropic), Gemini (Google).
"""
from abc import ABC, abstractmethod
from typing import List, Optional
import os, json, logging

log = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract interface for LLM backends."""

    @abstractmethod
    def chat(self, messages: list, model: str = None, **kwargs) -> str:
        """Send a chat completion. Returns response text."""
        ...

    def embed(self, text: str, **kwargs) -> List[float]:
        """Generate embedding vector (optional)."""
        raise NotImplementedError("Embeddings not supported by this provider")

    def list_models(self) -> List[str]:
        """List available models (optional)."""
        return []


# ── OpenAI-compatible (also covers DeepSeek, etc.) ─────────────────────────

class OpenAIProvider(LLMProvider):
    def __init__(self, api_base: str = None, api_key: str = None, model: str = "gpt-4o"):
        self.api_base = (api_base or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model

    def chat(self, messages, model=None, **kwargs):
        import requests
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": model or self._model, "messages": messages, **kwargs},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ── Ollama ──────────────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5"):
        self.base_url = base_url.rstrip("/")
        self._model = model

    def chat(self, messages, model=None, **kwargs):
        import requests
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={"model": model or self._model, "messages": messages, "stream": False, **kwargs},
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def embed(self, text, **kwargs):
        import requests
        resp = requests.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self._model, "prompt": text},
        )
        return resp.json()["embedding"]


# ── Claude (Anthropic) ──────────────────────────────────────────────────────

class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model

    def chat(self, messages, model=None, **kwargs):
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=model or self._model,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return resp.content[0].text


# ── Gemini (Google) ─────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str = None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self._model = model

    def chat(self, messages, model=None, **kwargs):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        m = genai.GenerativeModel(model or self._model)
        resp = m.generate_content(messages[-1]["content"])
        return resp.text


# ── Factory ─────────────────────────────────────────────────────────────────

def get_provider(backend: str = None, config: dict = None) -> LLMProvider:
    """Factory: returns the appropriate LLM provider."""
    cfg = config or {}
    backend = backend or cfg.get("backend", "openai_compatible")

    if backend == "ollama":
        return OllamaProvider(
            base_url=cfg.get("ollama", {}).get("base_url", "http://localhost:11434"),
            model=cfg.get("ollama", {}).get("model", "qwen2.5"),
        )
    elif backend == "claude":
        return ClaudeProvider(
            api_key=cfg.get("claude", {}).get("api_key"),
            model=cfg.get("claude", {}).get("model", "claude-sonnet-4-20250514"),
        )
    elif backend == "gemini":
        return GeminiProvider(
            api_key=cfg.get("gemini", {}).get("api_key"),
            model=cfg.get("gemini", {}).get("model", "gemini-2.0-flash"),
        )
    else:
        return OpenAIProvider(
            api_base=cfg.get("openai_compatible", {}).get("api_base", "https://api.openai.com/v1"),
            api_key=cfg.get("openai_compatible", {}).get("api_key"),
            model=cfg.get("openai_compatible", {}).get("model", "gpt-4o"),
        )
