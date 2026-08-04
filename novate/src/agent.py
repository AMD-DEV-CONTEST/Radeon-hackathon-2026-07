"""
Nova's orchestration layer.

Routing strategy: a lightweight, transparent intent router rather than a
black-box function-calling loop. This keeps behavior auditable (important
for a "private" agent) and keeps latency low, since we don't burn an extra
LLM round-trip just to decide whether to call a tool.

Pipeline for each user turn:
  1. Route: does this look like a tool request, a knowledge-base question,
     or general chat?
  2. Gather context: run the matched tool, or retrieve RAG chunks, or none.
  3. Build a grounded prompt including recent conversation memory.
  4. Call the local LLM (running on the AMD Radeon GPU) and return the answer.
  5. Record the turn in memory.
"""
from __future__ import annotations

import logging
import re

import config
from src.llm_client import LocalLLMClient
from src.memory import ConversationMemory
from src.tools import TOOL_REGISTRY
from src.vectorstore import VectorStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Nova, a private, locally-run research assistant. You only use "
    "information provided in your context (retrieved documents or tool "
    "output) and your own reasoning. If the context doesn't contain the "
    "answer, say so plainly instead of guessing. Be concise."
)

_TOOL_PATTERNS = {
    "list_files": re.compile(r"\b(list|show)\b.*\b(files|documents|docs)\b", re.I),
    "read_file": re.compile(r"\bread\b.*\bfile\b[: ]*(?P<arg>[\w\-. ]+\.\w+)", re.I),
    "calculator": re.compile(r"\bcalculate\b[: ]*(?P<arg>[\d\.\+\-\*/\(\) ]+)", re.I),
}


class NovaAgent:
    """Ties together routing, RAG, tools, memory, and the local LLM."""

    def __init__(
        self,
        llm_client: LocalLLMClient | None = None,
        vector_store: VectorStore | None = None,
        memory: ConversationMemory | None = None,
    ) -> None:
        self.llm = llm_client or LocalLLMClient()
        self.store = vector_store or VectorStore()
        self.memory = memory or ConversationMemory()

    def _route(self, query: str) -> tuple[str | None, str]:
        """Return (tool_name_or_None, extracted_argument)."""
        for tool_name, pattern in _TOOL_PATTERNS.items():
            match = pattern.search(query)
            if match:
                arg = match.groupdict().get("arg", "").strip() if match.groups() else ""
                return tool_name, arg
        return None, ""

    def _build_context_block(self, query: str) -> tuple[str, list[str]]:
        """Decide what grounding context to attach: a tool result or RAG chunks."""
        tool_name, arg = self._route(query)
        if tool_name:
            handler = TOOL_REGISTRY[tool_name]
            result = handler(arg)
            logger.info("Routed to tool '%s' (arg=%r)", tool_name, arg)
            return f"[Tool: {tool_name}]\n{result}", [f"tool:{tool_name}"]

        # Fall back to RAG if the knowledge base has anything indexed.
        if self.store.count() > 0:
            hits = self.store.query(query, top_k=config.RAG_TOP_K)
            if hits:
                context = "\n\n".join(
                    f"(source: {source})\n{chunk}" for chunk, source, _dist in hits
                )
                sources = sorted({source for _c, source, _d in hits})
                return f"[Retrieved context]\n{context}", sources

        return "", []

    def ask(self, query: str) -> dict:
        """Process one user turn end-to-end. Returns answer + trace metadata."""
        context_block, sources = self._build_context_block(query)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.memory.as_messages())
        if context_block:
            messages.append({"role": "system", "content": context_block})
        messages.append({"role": "user", "content": query})

        answer = self.llm.chat(messages)

        self.memory.add_turn("user", query)
        self.memory.add_turn("assistant", answer)

        return {"answer": answer, "sources": sources, "used_context": bool(context_block)}
