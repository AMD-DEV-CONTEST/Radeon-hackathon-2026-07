"""Optional explanation adapter for deterministic business-agent decisions.

Rules and scoring own all structured decisions. A local OpenAI-compatible vLLM
may only improve the explanation text or stable ranking notes. Tests use the
deterministic adapter and therefore need neither a GPU nor network access.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.evidence.model_client import LocalVLLMClient, strict_json


class AgentModelAdapter(Protocol):
    name: str

    def explain(self, agent_name: str, payload: dict[str, Any]) -> str: ...


class DeterministicAgentModelAdapter:
    name = "deterministic-test-adapter"

    def explain(self, agent_name: str, payload: dict[str, Any]) -> str:
        trace = payload.get("summary") or payload.get("scoring_trace") or {}
        rendered = json.dumps(
            trace, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return (
            f"{agent_name} 使用确定性事实约束与版本化规则生成；"
            f"结构化追踪={rendered[:500]}"
        )


class LocalVLLMAgentModelAdapter:
    """Local-only adapter; LocalVLLMClient rejects non-loopback endpoints."""

    name = "local-vllm-openai-compatible"

    def __init__(
        self,
        client: LocalVLLMClient | None = None,
        *,
        max_tokens: int = 600,
    ):
        self.client = client or LocalVLLMClient()
        self.max_tokens = max_tokens

    def explain(self, agent_name: str, payload: dict[str, Any]) -> str:
        call = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你只解释给定结构化结论，不新增事实、Evidence ID、"
                        "Fact ID、Law ID、责任比例或金额。禁止使用“必然”"
                        "“一定主责”“保证胜诉”“保险公司一定少赔”。"
                        '严格输出 {"explanation":"..."}。'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"agent": agent_name, "payload": payload},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ],
            max_tokens=self.max_tokens,
            temperature=0.0,
        )
        explanation = strict_json(call.content).get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError("Local adapter returned no explanation string.")
        return explanation.strip()
