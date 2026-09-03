"""LLM 客户端封装。

通过 OpenAI 兼容接口调用大模型。
MVP 阶段支持两种模式：
1. 真实 API:  配置 AUTOFLOW_LLM_API_KEY 等环境变量
2. Mock 模式: 未配置 API key 时使用本地规则生成计划，便于无网络演示
"""

from __future__ import annotations

import json
from typing import Any

from autoflow.config import get_settings


class LLMClient:
    """OpenAI 兼容接口客户端。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._openai = None
        if self.settings.llm_api_key:
            try:
                from openai import OpenAI

                self._openai = OpenAI(
                    api_key=self.settings.llm_api_key,
                    base_url=self.settings.llm_base_url,
                )
            except ImportError:
                self._openai = None

    @property
    def available(self) -> bool:
        return self._openai is not None

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 LLM 并解析 JSON 输出。

        Raises:
            RuntimeError: 未配置 API key 或模型返回非法 JSON。
        """
        if not self._openai:
            raise RuntimeError(
                "未配置 LLM API key。请设置 AUTOFLOW_LLM_API_KEY 环境变量，"
                "或使用 mock 模式 (autoflow planner --mock)。"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {"model": self.settings.llm_model, "messages": messages}
        if response_format:
            kwargs["response_format"] = response_format

        resp = self._openai.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content
        # 兼容可能被 ```json ... ``` 包裹的情况
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM 返回非法 JSON: {exc}") from exc
