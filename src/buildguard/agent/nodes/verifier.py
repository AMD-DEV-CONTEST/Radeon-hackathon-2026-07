"""Execution verification node."""

import json

from buildguard.agent.nodes.prompts import load_prompt
from buildguard.agent.state import AgentState, VerificationResult
from buildguard.llm.base import ChatMessage, LocalLLMBackend


def verify_result(state: AgentState, backend: LocalLLMBackend) -> dict[str, object]:
    plan_size = len(state["plan"].steps) if state["plan"] is not None else 0
    current_results = state["tool_results"][-plan_size:] if plan_size else []
    status_summary = ", ".join(
        f"success={result.success}" for result in current_results
    )
    detail_summary = json.dumps(
        [
            {
                "success": result.success,
                "error": result.error,
                "output": result.output,
            }
            for result in current_results
        ],
        ensure_ascii=False,
        default=str,
    )[:12_000]
    summary = f"{status_summary}; details={detail_summary}"
    if state["retry_count"]:
        summary += " replanned"
    prompt = f"{load_prompt('verifier.txt')}\nResults: {summary}"
    verification = backend.structured_chat(
        [ChatMessage(role="user", content=prompt)],
        VerificationResult,
        thinking=False,
        profile="structured_plan",
    )
    trace = [*state["performance_trace"], *getattr(backend, "metrics_history", [])[-1:]]
    errors = state["errors"]
    if not verification.valid and not errors:
        errors = [verification.reason]
    return {
        "errors": errors,
        "status": "verified"
        if verification.valid
        else ("recoverable_error" if verification.recoverable else "safe_failure"),
        "performance_trace": trace,
    }
