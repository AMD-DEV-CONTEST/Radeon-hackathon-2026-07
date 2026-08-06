"""Context builder with dual token budget (16K / 32K).

Manages token allocation across system prompt, repo structure,
conversation history, tool results, and response margin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..backend import ChatMessage
from .prompts import build_system_prompt

# Token budgets for the two operating modes.
# BUDGET_32K applies if FP8 weights are verified (max_model_len=32768).
# BUDGET_16K is the conservative default (max_model_len=16384).
BUDGET_32K = {
    "system_prompt": 1500,
    "repo_structure": 1000,
    "conversation": 4000,
    "tool_results": 17000,
    "response_margin": 9268,  # 32768 - (sum above)
}

BUDGET_16K = {
    "system_prompt": 1200,
    "repo_structure": 800,
    "conversation": 2000,
    "tool_results": 9000,
    "response_margin": 3384,  # 16384 - (sum above)
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per 4 chars for code/mixed text."""
    return len(text) // 4


def estimate_messages_tokens(messages: list[ChatMessage]) -> int:
    """Estimate total tokens for a list of messages (including role overhead)."""
    total = 0
    for msg in messages:
        total += 4  # role + formatting overhead per message
        total += estimate_tokens(msg.content)
        if msg.tool_calls:
            import json
            total += estimate_tokens(json.dumps(msg.tool_calls))
    return total


def build_repo_tree(repo_path: str | Path, max_depth: int = 2, max_lines: int = 60) -> str:
    """Build a compact directory tree string for the system prompt."""
    repo_path = Path(repo_path)
    lines: list[str] = []

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if len(lines) >= max_lines or depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return

        exclude = {".git", "node_modules", "__pycache__", ".venv", "dist", "build",
                    ".raa", "models"}
        for entry in entries:
            if entry.name in exclude or entry.name.startswith("."):
                continue
            if len(lines) >= max_lines:
                lines.append(f"{prefix}... (truncated)")
                return
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                _walk(entry, prefix + "  ", depth + 1)
            else:
                lines.append(f"{prefix}{entry.name}")

    _walk(repo_path, "", 1)
    return "\n".join(lines) if lines else "(empty or inaccessible)"


class ContextBuilder:
    """Assembles the message list for the LLM within token budget."""

    def __init__(self, budget: dict[str, int] | None = None) -> None:
        self.budget = budget or BUDGET_16K

    def build(
        self,
        repo_path: str,
        conversation: list[ChatMessage],
        user_query: str,
    ) -> list[ChatMessage]:
        """Build the full message list for an LLM call.

        Includes:
        1. System prompt (with repo tree)
        2. Truncated conversation history
        3. Current user query
        """
        # Build repo tree
        repo_tree = build_repo_tree(repo_path, max_depth=2)

        # Truncate repo tree if too long
        tree_tokens = estimate_tokens(repo_tree)
        max_tree = self.budget["repo_structure"]
        if tree_tokens > max_tree:
            # Truncate by lines
            while estimate_tokens(repo_tree) > max_tree and "\n" in repo_tree:
                repo_tree = repo_tree.rsplit("\n", 1)[0]
            repo_tree += "\n... (truncated)"

        system = build_system_prompt(str(repo_path), repo_tree)

        # Truncate conversation history to fit budget
        conv_budget = self.budget["conversation"]
        conv_messages: list[ChatMessage] = []
        remaining = conv_budget
        for msg in reversed(conversation):
            msg_tokens = estimate_tokens(msg.content) + 4
            if remaining < msg_tokens:
                break
            conv_messages.insert(0, msg)
            remaining -= msg_tokens

        # Assemble messages
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system),
        ]
        messages.extend(conv_messages)
        messages.append(ChatMessage(role="user", content=user_query))

        return messages

    @property
    def max_model_len(self) -> int:
        return sum(self.budget.values())


def budget_for_context_len(context_len: int) -> dict[str, int]:
    """Select the appropriate budget table for a context length."""
    if context_len >= 32768:
        return BUDGET_32K
    return BUDGET_16K
