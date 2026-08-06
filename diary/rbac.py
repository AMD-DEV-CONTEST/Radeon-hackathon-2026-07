"""RBAC / tool allowlist for the diary agent.

The diary runs locally, so RBAC is a set of *defensive guardrails* on what the
LLM-driven agent may do through the graph: it can record/read entries, manage todos,
and search, but it can NEVER delete days/entries, modify RBAC, or touch other graphs.

Enforcement happens at the tool layer (``diary.tools.TOOLS``): only the tools
registered there are callable. Destructive / maintenance operations are simply absent
from the registry, so the agent cannot invoke them.
"""

from __future__ import annotations


class RBACViolation(PermissionError):
    """Raised when the agent requests a tool it is not permitted to use."""


# Tools the agent is allowed to invoke. Delete/maintenance ops are intentionally absent.
AGENT_TOOLS = {
    "read_day",
    "record_entry",
    "add_todo",
    "get_todos",
    "search_graph",
    "summarize_day",
}


def assert_allowed(tool_name: str) -> None:
    if tool_name not in AGENT_TOOLS:
        raise RBACViolation(f"agent not permitted to use tool '{tool_name}'")
