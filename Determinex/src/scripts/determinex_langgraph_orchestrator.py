#!/usr/bin/env python3
"""determinex_langgraph_orchestrator.py — LangGraph multi-agent skeleton.

Replaces the hand-rolled Architect / Builder / Monitor in determinex_hive.py
with a graph-based orchestrator that supports:
- Conditional routing (if compile fails → Architect retry / escalation)
- Parallel agent execution
- Persistent state via Postgres/Redis checkpointer
- Observability via OpenTelemetry spans

State graph:
    start → architect → builder → compile_oracle
                          ↑           ↓
                          └── monitor ─┘  (on fail, route back to architect)
                                      ↓
                                  oracle_pass → end

Run:
    python scripts/determinex_langgraph_orchestrator.py --spec my_spec.md --lang rust

Requires:
    pip install langgraph langchain-core langchain-openai
"""

from __future__ import annotations

import argparse
import operator
import sys
from pathlib import Path
from typing import Annotated, TypedDict


class DeterminexState(TypedDict):
    spec: str
    lang: str
    plan: list[dict]
    current_step: int
    last_patch: str
    last_compile_output: str
    last_compile_rc: int
    retry_count: int
    max_retries: int
    final_artifact: str
    log: Annotated[list[str], operator.add]


def architect_node(state: DeterminexState) -> dict:
    """Architect: produces a DAG of build steps OR retries with compile feedback."""
    log = [f"[architect] planning (retry={state.get('retry_count', 0)})"]
    # In production, call C7 Sentinel via ollama HTTP API
    if state.get("last_compile_rc", 0) != 0 and state.get("retry_count", 0) > 0:
        log.append(f"[architect] incorporating compile error: {state['last_compile_output'][:200]}")

    # Stub plan — real impl reads spec.md and calls LLM
    plan = [
        {"step": 1, "action": "scaffold", "files": ["src/lib.rs"], "intent": "core function"},
        {"step": 2, "action": "test", "files": ["tests/test.rs"], "intent": "verify"},
    ]
    return {"plan": plan, "current_step": 0, "log": log}


def builder_node(state: DeterminexState) -> dict:
    """Builder: emits code for current step."""
    log = [f"[builder] generating step {state['current_step']}"]
    # In production, call C1 Engineer via ollama
    step = state["plan"][state["current_step"]]
    # Stub patch
    patch = f"# stub patch for step {step['step']}: {step['intent']}\n"
    return {"last_patch": patch, "log": log}


def compile_oracle_node(state: DeterminexState) -> dict:
    """Compile Oracle: deterministic verdict via rustc/go/python/tsc."""
    log = ["[oracle] compile check"]
    # In production, write patch to git worktree + run language compiler
    # Stub: pretend it succeeded
    rc = 0
    output = "ok"
    return {"last_compile_rc": rc, "last_compile_output": output, "log": log}


def monitor_node(state: DeterminexState) -> dict:
    """Monitor: scores patch quality, decides next route."""
    log = [f"[monitor] step {state['current_step']} rc={state['last_compile_rc']}"]
    if state["last_compile_rc"] == 0:
        log.append("[monitor] PASS → advance")
        return {"current_step": state["current_step"] + 1, "retry_count": 0, "log": log}
    else:
        retry = state.get("retry_count", 0) + 1
        log.append(f"[monitor] FAIL → retry {retry}/{state['max_retries']}")
        return {"retry_count": retry, "log": log}


def route_decision(state: DeterminexState) -> str:
    if state["last_compile_rc"] == 0:
        if state["current_step"] >= len(state["plan"]):
            return "done"
        return "next_step"
    if state.get("retry_count", 0) >= state.get("max_retries", 3):
        return "escalate"
    return "retry_architect"


def build_graph():
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        print("Install langgraph: pip install langgraph langchain-core")
        sys.exit(1)

    g = StateGraph(DeterminexState)
    g.add_node("architect", architect_node)
    g.add_node("builder", builder_node)
    g.add_node("oracle", compile_oracle_node)
    g.add_node("monitor", monitor_node)

    g.set_entry_point("architect")
    g.add_edge("architect", "builder")
    g.add_edge("builder", "oracle")
    g.add_edge("oracle", "monitor")
    g.add_conditional_edges(
        "monitor",
        route_decision,
        {
            "next_step": "builder",
            "retry_architect": "architect",
            "done": END,
            "escalate": END,
        },
    )
    return g.compile()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--lang", default="rust")
    ap.add_argument("--max-retries", type=int, default=3)
    args = ap.parse_args()

    spec_text = Path(args.spec).read_text(encoding="utf-8")
    initial: DeterminexState = {
        "spec": spec_text,
        "lang": args.lang,
        "plan": [],
        "current_step": 0,
        "last_patch": "",
        "last_compile_output": "",
        "last_compile_rc": 0,
        "retry_count": 0,
        "max_retries": args.max_retries,
        "final_artifact": "",
        "log": [],
    }
    graph = build_graph()
    final = graph.invoke(initial)
    for line in final["log"]:
        print(line)
    print(
        f"\nFinal state: step={final['current_step']}/{len(final['plan'])} retries={final['retry_count']}"
    )


if __name__ == "__main__":
    main()
