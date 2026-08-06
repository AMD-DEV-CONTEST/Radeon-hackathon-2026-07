"""本地 Ollama 后端（OpenAI 兼容 /v1/chat/completions）。

Ollama 的 OpenAI 兼容端点默认在 http://localhost:11434/v1（需 Ollama 开启
`ollama serve` 并启用兼容模式）。本后端复用 OpenAICompatBackend 的端点归一化
与 SSE，把 provider=ollama 的注册表条目映射到正确后端实例。
"""

from __future__ import annotations

from .openai_compat_backend import OpenAICompatBackend

OLLAMA_DEFAULT_URL = "http://localhost:11434/v1"


class OllamaBackend(OpenAICompatBackend):
    """本地 Ollama 后端（OpenAI 兼容模式）。"""

    name = "ollama"

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = OLLAMA_DEFAULT_URL,
        timeout: int = 120,
    ):
        super().__init__(api_key=api_key, model=model, base_url=base_url, timeout=timeout)
