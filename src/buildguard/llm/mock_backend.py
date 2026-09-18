"""Deterministic backend for offline program verification."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator, Sequence
from typing import Any

from buildguard.llm.base import (
    ChatMessage,
    GenerationProfileName,
    LocalLLMBackend,
    StructuredT,
)
from buildguard.llm.structured_output import parse_structured
from buildguard.llm.token_metrics import ChatResponse, TokenMetrics


class MockLLMBackend(LocalLLMBackend):
    """Keyword-driven, deterministic responses; never a quality benchmark."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.calls = 0
        self.metrics_history: list[TokenMetrics] = []

    def _content(self, messages: Sequence[ChatMessage]) -> str:
        content = messages[-1].content.lower()
        query = content.rsplit("user query:", 1)[-1]
        if "inspection analysis request" in content:
            match = re.search(r"canonical labels:\s*(\[[^\n]*\])", content)
            labels = json.loads(match.group(1)) if match else []
            return json.dumps(
                {
                    "search_standards": bool(labels),
                    "standards_query": (
                        "施工安全规范 " + " ".join(str(item) for item in labels)
                        if labels
                        else None
                    ),
                    "query_history": "历史" in query or "重复" in query,
                    "history_limit": 20,
                    "reason": "mock post-vision evidence decision",
                },
                ensure_ascii=False,
            )
        if "intent request" in content:
            category = "history" if "history" in query or "历史" in query else "inspection"
            complexity = "multi_step" if "multi" in query or "多步" in query else "simple"
            return json.dumps({"category": category, "complexity": complexity, "confidence": 1.0})
        if "plan request" in content:
            steps: list[dict[str, Any]]
            if "requested action hint: event_report" in content:
                steps = [
                    {
                        "step_id": "s1",
                        "description": "generate realtime event report",
                        "tool_name": "generate_event_report",
                        "arguments": {"session_id": "$session.id"},
                        "requires_confirmation": True,
                    }
                ]
            elif "requested action hint: report" in content:
                steps = [
                    {
                        "step_id": "s1",
                        "description": "generate inspection report",
                        "tool_name": "generate_inspection_report",
                        "arguments": {"session_id": "$session.id"},
                        "requires_confirmation": True,
                    }
                ]
            elif "requested action hint: history" in content or "高风险" in query:
                steps = [
                    {
                        "step_id": "s1",
                        "description": "query inspection history",
                        "tool_name": "query_task_history",
                        "arguments": {"session_id": "$session.id", "limit": 20},
                    }
                ]
            elif "illegal" in query or "非法" in query:
                steps = [{"step_id": "s1", "description": "illegal", "tool_name": "shell"}]
            elif "cycle" in query or "循环" in query:
                steps = [
                    {"step_id": "s1", "description": "one", "tool_name": "echo", "depends_on": ["s2"]},
                    {"step_id": "s2", "description": "two", "tool_name": "echo", "depends_on": ["s1"]},
                ]
            elif "multi" in query or "多步" in query:
                steps = [
                    {
                        "step_id": "s1",
                        "description": "inspect",
                        "tool_name": "echo",
                        "arguments": {"text": "$user.query"},
                    },
                    {
                        "step_id": "s2",
                        "description": "summarize",
                        "tool_name": "echo",
                        "arguments": {"text": "$steps.s1.output.text"},
                        "depends_on": ["s1"],
                    },
                ]
            else:
                tool = "inspect_image" if "confirm" in query or "确认" in query else "echo"
                steps = [
                    {
                        "step_id": "s1",
                        "description": "execute request",
                        "tool_name": tool,
                        "arguments": {"text": "$user.query"},
                    }
                ]
            return json.dumps({"goal": "Handle local request", "steps": steps})
        if "verify request" in content:
            failed = "success=false" in content
            return json.dumps(
                {"valid": not failed, "recoverable": failed, "reason": "mock verification"}
            )
        return "Local mock response completed."

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> ChatResponse:
        started = time.perf_counter()
        self.calls += 1
        content = self._content(messages)
        elapsed = time.perf_counter() - started
        completion = max(1, len(content.split()))
        metrics = TokenMetrics(
            prompt_tokens=sum(len(message.content.split()) for message in messages),
            completion_tokens=completion,
            total_tokens=sum(len(message.content.split()) for message in messages) + completion,
            ttft_seconds=0,
            total_seconds=elapsed,
            tokens_per_second=completion / elapsed if elapsed else 0,
            thinking_mode=thinking,
        )
        self.metrics_history.append(metrics)
        return ChatResponse(content=content, metrics=metrics)

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> Iterator[str]:
        yield self.chat(messages, thinking=thinking, profile=profile).content

    def structured_chat(
        self,
        messages: Sequence[ChatMessage],
        schema: type[StructuredT],
        *,
        thinking: bool = False,
        profile: GenerationProfileName | None = None,
    ) -> StructuredT:
        return parse_structured(
            self.chat(messages, thinking=thinking, profile=profile).content, schema
        )

    def health_check(self) -> bool:
        return True
