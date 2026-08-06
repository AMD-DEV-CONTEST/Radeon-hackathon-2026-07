"""本地 llama.cpp server 后端（OpenAI 兼容 /v1/chat/completions）。

llama.cpp server 默认监听 http://127.0.0.1:11434/v1，其 /v1/models 暴露本地模型，
聊天走 /v1/chat/completions。本后端复用 OpenAICompatBackend 的端点归一化与 SSE，
只负责把 provider=llamacpp 的注册表条目映射到正确的后端实例。

无需 API key（llama.cpp server 一般不鉴权），api_key 传占位串即可。
"""

from __future__ import annotations

from .openai_compat_backend import OpenAICompatBackend

LLAMACPP_DEFAULT_URL = "http://127.0.0.1:11434/v1"


class LlamaCppBackend(OpenAICompatBackend):
    """本地 llama.cpp server 后端。"""

    name = "llamacpp"

    def __init__(
        self,
        api_key: str = "llamacpp",
        model: str = "",
        base_url: str = LLAMACPP_DEFAULT_URL,
        timeout: int = 120,
    ):
        super().__init__(api_key=api_key, model=model, base_url=base_url, timeout=timeout)
