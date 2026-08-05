"""
THEMIS Shared Types
All TypedDicts and shared utilities imported by both orchestrator and agents.
Lives here to avoid circular imports.
"""

import operator
import json
import time
from hashlib import sha256
from typing import Annotated, Any
from typing_extensions import TypedDict


# ── Finding Schema ────────────────────────────────────────────

class Finding(TypedDict):
    id: str
    agent: str
    category: str          # "security" | "style" | "quality"
    severity: str          # "critical" | "high" | "medium" | "low"
    title: str
    description: str
    file: str
    line: int | None
    cwe_id: str | None     # e.g. "CWE-89"
    confidence: float      # 0.0 – 1.0
    evidence: str          # Code snippet or tool output


# ── Graph State ───────────────────────────────────────────────

def max_step(a: int, b: int) -> int:
    return max(a or 0, b or 0)


class ThemisState(TypedDict):
    # ── Input ────────────────────────────────────────────────
    diff: str
    sanitized_diff: str
    repo: str
    pr_number: int
    pr_metadata: dict

    # ── Agent outputs (list reducers — safe parallel merge) ──
    security_findings: Annotated[list[Finding], operator.add]
    style_findings: Annotated[list[Finding], operator.add]
    errors: Annotated[list[str], operator.add]

    # ── Verifier output ──────────────────────────────────────
    verified_findings: list[Finding]
    confidence_scores: dict[str, float]

    # ── Fix output ───────────────────────────────────────────
    patches: list[dict]
    fix_pr_url: str | None

    # ── Triage metadata ──────────────────────────────────────
    file_types: list[str]
    risk_score: float
    chunked_diffs: list[str]

    # ── Loop guards ──────────────────────────────────────────
    visited_tool_hashes: set
    step_count: Annotated[int, max_step]

    # ── Streaming events (appended by each agent) ────────────
    events: Annotated[list[dict], operator.add]

    # ── Human approval gate ──────────────────────────────────
    human_approved: bool


# ── Shared Utilities ──────────────────────────────────────────

def make_event(agent: str, event_type: str, data: Any) -> dict:
    """Create a structured WebSocket event for the frontend Tribunal View."""
    return {
        "agent": agent,
        "type": event_type,   # "start" | "thinking" | "tool_call" | "finding" | "done" | "error"
        "data": data,
        "timestamp": time.time(),
    }


def detect_loop(state: ThemisState, tool: str, args: dict) -> bool:
    """Return True if this exact tool+args combination was already executed."""
    call_hash = sha256(
        f"{tool}:{json.dumps(args, sort_keys=True)}".encode()
    ).hexdigest()
    if call_hash in state.get("visited_tool_hashes", set()):
        return True
    return False
