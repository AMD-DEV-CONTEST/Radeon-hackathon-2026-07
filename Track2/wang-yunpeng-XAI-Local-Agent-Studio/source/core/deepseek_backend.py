"""真实 DeepSeek 后端（OpenAI 兼容 /v1/chat/completions）。

这是 XAI「模型无关」架构的真正落点：Grok 之前接的 DeepSeek key 被放在
~/.zshrc 的环境变量 DEEPSEEK_API_KEY 里，本后端直接读它 —— **无需落盘、无需
改任何上层逻辑**。换模型/换 key 只需换一个 Backend 实现。

底层复用 OpenAICompatBackend（已修复 /chat/completions 端点归一化），
因此本地 llama.cpp / Ollama 可共用同一套 HTTP + SSE 实现。

上层（reason / meta / control_loop / intent_router / workflow_bridge）全部只依赖
`ModelBackend` 抽象，因此接真模型后 73 个单测与架构纹丝不动。
"""

from __future__ import annotations

import os
from typing import Optional

from .openai_compat_backend import OpenAICompatBackend

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


class DeepSeekBackend(OpenAICompatBackend):
    """通过环境变量 DEEPSEEK_API_KEY 接入真实 DeepSeek 模型。"""

    name = "deepseek"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-v4-flash",
        base_url: str = DEEPSEEK_API_URL,
        timeout: int = 60,
    ):
        resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "缺少 DEEPSEEK_API_KEY：请在环境（~/.zshrc）或参数中提供 DeepSeek key"
            )
        super().__init__(api_key=resolved_key, model=model, base_url=base_url, timeout=timeout)
