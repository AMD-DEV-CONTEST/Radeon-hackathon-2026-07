"""ReAct Agent engine v3: text-based tool calling.

vLLM's hermes parser doesn't work reliably with Qwen2.5 on gfx1100.
Instead of fighting vLLM's OpenAI tool_call format validation, we:
1. Describe tools in the system prompt (model outputs bare JSON tool calls)
2. Parse tool calls from text output ourselves
3. Feed tool results back as role="user" messages (no role="tool")
4. Never send tools= parameter to vLLM (avoids all hermes parser issues)

This is simpler, more portable (works with llama.cpp too), and more
robust for models that don't have perfect function calling support.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

from ..backend import LLMBackend, ChatMessage
from ..tool_parser import parse_tool_calls
from ..tools.registry import ToolRegistry
from .context import ContextBuilder, BUDGET_16K, BUDGET_32K, estimate_tokens, budget_for_context_len

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TEXT = "text"
    TEXT_DELTA = "text_delta"
    PROGRESS = "progress"
    DONE = "done"
    ERROR = "error"


@dataclass
class AgentEvent:
    type: EventType
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        payload = {"type": self.type.value, "content": self.content}
        payload.update(self.data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@dataclass
class AgentConfig:
    max_iterations: int = 8
    temperature: float = 0.3
    top_p: float = 0.9
    max_tokens: int = 4096
    context_budget: dict[str, int] = field(default_factory=lambda: BUDGET_16K)


class AgentEngine:
    """ReAct engine with streaming and text-based tool calling."""

    def __init__(
        self,
        backend: LLMBackend,
        registry: ToolRegistry,
        repo_path: str,
        config: AgentConfig | None = None,
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.repo_path = repo_path
        self.config = config or AgentConfig()
        self.context_builder = ContextBuilder(self.config.context_budget)

    async def run(
        self,
        query: str,
        history: list[ChatMessage] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the ReAct loop with streaming."""
        history = history or []
        tool_names = set(self.registry.list_tools())
        tool_result_budget = self.config.context_budget.get("tool_results", 9000)
        messages = self.context_builder.build(self.repo_path, history, query)

        for iteration in range(1, self.config.max_iterations + 1):
            logger.info("Agent iteration %d/%d", iteration, self.config.max_iterations)

            # ── Stream the LLM response (NO tools= parameter) ──
            full_text = ""
            try:
                async for delta in self.backend.stream_chat(
                    messages=messages,
                    tools=None,  # text-based, not OpenAI tools API
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                ):
                    chunk = delta.get("content", "")
                    if chunk:
                        full_text += chunk
                        yield AgentEvent(
                            type=EventType.TEXT_DELTA,
                            content=chunk,
                            data={"iteration": iteration},
                        )
                    if delta.get("finish_reason"):
                        break

            except Exception as e:
                logger.error("LLM stream failed: %s", e)
                yield AgentEvent(type=EventType.ERROR, content=f"LLM error: {e}")
                return

            # ── Parse for tool calls from text ──
            result = parse_tool_calls(
                message={"content": full_text, "tool_calls": []},
                full_text=full_text,
                prefer_structured=False,
            )

            valid_calls = [tc for tc in result.calls if tc.name in tool_names]

            logger.info("Parsed %d tool calls from %d chars of text", len(result.calls), len(full_text))
            if not valid_calls:
                # No tool calls — this is the final answer
                final_text = full_text.strip()
                yield AgentEvent(type=EventType.TEXT, content=final_text)
                yield AgentEvent(type=EventType.DONE, content=final_text)
                return

            # ── Valid tool calls found in text ──
            # The streamed text was reasoning, emit as thinking
            yield AgentEvent(
                type=EventType.THINKING,
                content=result.text_before or full_text,
                data={"iteration": iteration},
            )

            # Add assistant message (plain text, no structured tool_calls)
            messages.append(ChatMessage(role="assistant", content=full_text))

            # ── Execute tools, collect results ──
            tool_results: list[str] = []
            for tc in valid_calls:
                yield AgentEvent(
                    type=EventType.PROGRESS,
                    content=_tool_progress(tc.name, tc.arguments),
                    data={"tool": tc.name, "iteration": iteration},
                )
                yield AgentEvent(
                    type=EventType.TOOL_CALL,
                    content=tc.name,
                    data={"arguments": tc.arguments, "iteration": iteration},
                )

                tool_result = await self.registry.execute(tc.name, tc.arguments)

                # Truncate to fit budget
                if estimate_tokens(tool_result) > tool_result_budget:
                    max_chars = tool_result_budget * 4
                    tool_result = tool_result[:max_chars] + "\n\n... [truncated]"

                tool_results.append(f"[Tool: {tc.name}({json.dumps(tc.arguments)})]\n{tool_result}")

                display = tool_result[:1500] + "..." if len(tool_result) > 1500 else tool_result
                yield AgentEvent(
                    type=EventType.TOOL_RESULT,
                    content=display,
                    data={"tool": tc.name, "iteration": iteration},
                )

            # Feed tool results back as a single user message
            # (avoids vLLM role="tool" validation entirely)
            feedback = "\n\n".join(tool_results)
            feedback = f"Tool results:\n\n{feedback}\n\nBased on these results, either call another tool or give your final answer."
            messages.append(ChatMessage(role="user", content=feedback))

            # Trim conversation if approaching context limit
            total_tokens = sum(estimate_tokens(m.content) + 4 for m in messages)
            max_tokens = self.config.context_budget.get("tool_results", 9000) + \
                self.config.context_budget.get("conversation", 2000) + \
                self.config.context_budget.get("system_prompt", 1200) + \
                self.config.context_budget.get("repo_structure", 800)
            if total_tokens > max_tokens:
                logger.info("Context %d tokens > %d limit, trimming old messages", total_tokens, max_tokens)
                # Keep system prompt (index 0) and last 4 messages
                while len(messages) > 5 and estimate_tokens(
                    "\n".join(m.content for m in messages[1:-4])
                ) > max_tokens // 2:
                    messages.pop(1)  # Remove oldest non-system message
                logger.info("Trimmed to %d messages", len(messages))

        # Max iterations reached
        logger.warning("Agent reached max iterations (%d)", self.config.max_iterations)
        yield AgentEvent(
            type=EventType.TEXT,
            content="Based on my exploration of the code, I've gathered the relevant context. Here is my analysis.",
        )
        yield AgentEvent(type=EventType.DONE)


def _tool_progress(name: str, args: dict) -> str:
    """Human-readable progress message for tool execution."""
    if name == "search_code":
        return f"Searching codebase for: {args.get('query', '?')}"
    elif name == "grep_code":
        return f"Searching for pattern: {args.get('pattern', '?')}"
    elif name == "read_file":
        path = args.get("path", "?")
        lines = ""
        if args.get("start_line", 0) > 1:
            lines = f" (line {args['start_line']})"
        return f"Reading {path}{lines}"
    elif name == "get_symbols":
        return f"Extracting symbols from {args.get('path', '?')}"
    elif name == "find_references":
        return f"Finding references to: {args.get('name', '?')}"
    elif name == "list_directory":
        return f"Listing {args.get('path', '.')}"
    return f"Executing {name}..."


def _make_tool_call_id(tool_name: str, iteration: int) -> str:
    return f"call_{tool_name}_{iteration}"
