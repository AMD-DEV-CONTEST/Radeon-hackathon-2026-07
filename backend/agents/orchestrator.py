"""
THEMIS LangGraph Orchestrator — 5-Agent Tribunal
Team: Alchemy | AMD AI DevMaster Hackathon 2026

Pipeline: Triage → [Security || Style] → Verifier → Fix → [HITL Gate] → PR
"""

import operator
import json
import time
from typing import Any, AsyncGenerator

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.types import Finding, ThemisState, make_event, detect_loop
from backend.agents.triage_agent import triage_agent
from backend.agents.security_agent import security_agent
from backend.agents.style_agent import style_agent
from backend.agents.verifier_agent import verifier_agent
from backend.agents.fix_agent import fix_agent
from backend.config import get_settings

settings = get_settings()


# Finding, ThemisState, make_event, detect_loop are all in types.py



# ── Node Wrappers ────────────────────────────────────────────────────────────

async def run_triage(state: ThemisState) -> dict:
    """Triage node — parses diff, detects file types, chunks if needed."""
    event = make_event("triage", "start", {"message": "Parsing PR diff..."})
    result = await triage_agent(state)
    result["events"] = [event, make_event("triage", "done", {"file_count": len(result.get("file_types", []))})]
    result["step_count"] = state.get("step_count", 0) + 1
    return result


async def run_security(state: ThemisState) -> dict:
    """Security agent node — detects vulnerabilities."""
    event = make_event("security", "start", {"message": "Scanning for vulnerabilities..."})
    result = await security_agent(state)
    result["events"] = [
        event,
        make_event("security", "done", {"findings_count": len(result.get("security_findings", []))}),
    ]
    result["step_count"] = state.get("step_count", 0) + 1
    return result


async def run_style(state: ThemisState) -> dict:
    """Style agent node — detects code quality issues."""
    event = make_event("style", "start", {"message": "Checking code style..."})
    result = await style_agent(state)
    result["events"] = [
        event,
        make_event("style", "done", {"findings_count": len(result.get("style_findings", []))}),
    ]
    result["step_count"] = state.get("step_count", 0) + 1
    return result


async def run_verifier(state: ThemisState) -> dict:
    """Verifier agent — cross-checks findings, scores confidence."""
    event = make_event("verifier", "start", {"message": "Verifying findings..."})
    result = await verifier_agent(state)
    verified = result.get("verified_findings", [])
    sec_findings = state.get("security_findings") or []
    sty_findings = state.get("style_findings") or []
    result["events"] = [
        event,
        make_event("verifier", "done", {
            "verified_count": len(verified),
            "verified_findings": verified,
            "filtered_count": len(sec_findings + sty_findings) - len(verified),
        }),
    ]
    result["step_count"] = state.get("step_count", 0) + 1
    return result


async def run_fix(state: ThemisState) -> dict:
    """Fix agent — generates patches for verified findings."""
    event = make_event("fix", "start", {"message": "Generating patches..."})
    result = await fix_agent(state)
    patches = result.get("patches", [])
    result["events"] = [
        event,
        make_event("fix", "done", {
            "patches_count": len(patches),
            "patches": patches,
        }),
    ]
    result["step_count"] = state.get("step_count", 0) + 1
    return result


# ── Routing Logic ─────────────────────────────────────────────────────────────

def should_fix(state: ThemisState) -> str:
    """After verifier: if there are verified findings AND human approved, run fix."""
    verified = state.get("verified_findings") or []
    if not verified:
        return "end"
    if state.get("human_approved", False):
        return "fix"
    return "await_approval"  # HITL gate — pause for human decision


def after_fix(state: ThemisState) -> str:
    return "end"


# ── Graph Assembly ────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Assemble and compile the THEMIS 5-agent tribunal graph."""

    builder = StateGraph(ThemisState)

    # Register nodes
    builder.add_node("triage", run_triage)
    builder.add_node("security", run_security)
    builder.add_node("style", run_style)
    builder.add_node("verifier", run_verifier)
    builder.add_node("fix", run_fix)

    # Entry point
    builder.set_entry_point("triage")

    # Triage → parallel security + style
    builder.add_edge("triage", "security")
    builder.add_edge("triage", "style")

    # Both parallel branches → verifier (fan-in)
    builder.add_edge("security", "verifier")
    builder.add_edge("style", "verifier")

    # Verifier → conditional routing
    builder.add_conditional_edges(
        "verifier",
        should_fix,
        {
            "fix": "fix",
            "end": END,
            "await_approval": END,  # Frontend shows HITL gate
        },
    )

    # Fix → end
    builder.add_edge("fix", END)

    # Compile with memory checkpointer + safety limits
    return builder.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["fix"],  # Always pause before writing to GitHub
    )


# ── Public API ────────────────────────────────────────────────────────────────

# Singleton graph instance
_graph = None


def get_graph() -> StateGraph:
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_review(
    diff: str,
    sanitized_diff: str,
    repo: str,
    pr_number: int,
    pr_metadata: dict,
) -> AsyncGenerator[dict, None]:
    """
    Run the full THEMIS tribunal on a PR diff.
    Yields WebSocket events as each agent completes.

    Args:
        diff: Raw diff string
        sanitized_diff: Sanitized diff (prompt-injection-safe)
        repo: GitHub repo name (owner/repo)
        pr_number: PR number
        pr_metadata: Dict with title, author, branches, etc.

    Yields:
        Event dicts suitable for WebSocket streaming
    """
    graph = get_graph()

    initial_state: ThemisState = {
        "diff": diff,
        "sanitized_diff": sanitized_diff,
        "repo": repo,
        "pr_number": pr_number,
        "pr_metadata": pr_metadata,
        "security_findings": [],
        "style_findings": [],
        "errors": [],
        "verified_findings": [],
        "confidence_scores": {},
        "patches": [],
        "fix_pr_url": None,
        "file_types": [],
        "risk_score": 0.0,
        "chunked_diffs": [],
        "visited_tool_hashes": set(),
        "step_count": 0,
        "events": [],
        "human_approved": False,
    }

    config = {
        "configurable": {"thread_id": f"{repo}-{pr_number}-{int(time.time())}"},
        "recursion_limit": settings.agent_recursion_limit,
    }

    async for chunk in graph.astream(initial_state, config=config):
        for node_name, node_output in chunk.items():
            for event in node_output.get("events", []):
                yield event


async def approve_and_fix(thread_id: str) -> dict:
    """
    Resume the graph after human approval to trigger fix PR creation.
    Called by the frontend when user clicks 'Approve Fix'.
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}

    # Update state to mark human approval
    await graph.aupdate_state(
        config,
        {"human_approved": True},
        as_node="verifier",
    )

    # Resume from the interrupt point
    final_state = None
    async for chunk in graph.astream(None, config=config):
        for node_name, node_output in chunk.items():
            final_state = node_output

    return final_state or {}
