"""MCP-style tool layer for the diary agent (enforces RBAC).

Only the tools registered in ``TOOLS`` are callable via :func:`call_tool`; any other
name raises ``RBACViolation``. This is where the Cypher->Gremlin mismatch is absorbed
(the agent talks to stable tool names; the schema speaks Bionic-Graph's Gremlin API)
and where the agent's permissions are enforced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from database.bionic_graph_client import BionicGraphClient
from diary import rbac
from diary import schema as S


@dataclass
class DiaryContext:
    client: BionicGraphClient


def read_day(ctx: DiaryContext, date: str) -> dict:
    """Return the entries and todos attached to a day."""
    rbac.assert_allowed("read_day")
    client = ctx.client
    day_id = S.ensure_day(client, date)
    reached = client.gremlin(
        [{"step": "V", "ids": [day_id]}, {"step": "out", "depth": 1}]
    ) or []
    entries = [v for v in reached if S.L_ENTRY in (v.get("labels") or [])]
    todos = [v for v in reached if S.L_TODO in (v.get("labels") or [])]
    return {
        "date": date,
        "entries": [v.get("properties", {}).get("text", "") for v in entries],
        "todos": [v.get("properties", {}).get("text", "") for v in todos],
    }


def record_entry(
    ctx: DiaryContext,
    date: str,
    text: str,
    ts=None,
    lang: str = "zh",
    turn_id=None,
    mentions: list[dict] | None = None,
) -> int:
    """Record one spoken turn under `date` and link any extracted facets."""
    rbac.assert_allowed("record_entry")
    client = ctx.client
    day_id = S.ensure_day(client, date)
    eid = S.add_entry(client, day_id, text, ts=ts, lang=lang, turn_id=turn_id)
    for m in mentions or []:
        S.mention(client, eid, m["label"], m["key"], properties=m.get("properties"))
    return eid


def add_todo(ctx: DiaryContext, date: str, text: str, for_date: str | None = None) -> int:
    """Create a todo/plan under `date`; if `for_date` is set, point it forward."""
    rbac.assert_allowed("add_todo")
    client = ctx.client
    day_id = S.ensure_day(client, date)
    return S.add_todo(client, day_id, text, for_date=for_date)


def get_todos(ctx: DiaryContext, date: str) -> list:
    """Return Todo nodes attached to a day (used for the clarification check)."""
    rbac.assert_allowed("get_todos")
    client = ctx.client
    day_id = S.ensure_day(client, date)
    return S.todos_for_day(client, day_id)


def search_graph(ctx: DiaryContext, text: str, mode: str = "greedy", limit: int = 10) -> list:
    """Full-text search over the diary graph."""
    rbac.assert_allowed("search_graph")
    return ctx.client.search(text, mode=mode, limit=limit)


def summarize_day(ctx: DiaryContext, date: str) -> str:
    """Concatenate the day's entry texts (real LLM summarization lands in Slice 2)."""
    rbac.assert_allowed("summarize_day")
    day = read_day(ctx, date)
    return "\n".join(f"- {e}" for e in day["entries"] if e)


# -- registry (the RBAC boundary) -----------------------------------------
TOOLS = {
    "read_day": read_day,
    "record_entry": record_entry,
    "add_todo": add_todo,
    "get_todos": get_todos,
    "search_graph": search_graph,
    "summarize_day": summarize_day,
}


def call_tool(name: str, ctx: DiaryContext, **kwargs):
    if name not in TOOLS:
        raise rbac.RBACViolation(f"unknown or forbidden tool: {name}")
    return TOOLS[name](ctx, **kwargs)
