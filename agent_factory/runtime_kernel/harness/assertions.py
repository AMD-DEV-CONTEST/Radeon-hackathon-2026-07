from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class AssertPathContains:
    def __init__(self, expected_node_ids: Iterable[str]) -> None:
        self.expected_node_ids = list(expected_node_ids)

    def check(self, *, event_log: list[dict[str, Any]]) -> dict[str, Any]:
        seen = [item.get("node_id") for item in event_log if item.get("event_type") == "node_entered"]
        ok = all(node_id in seen for node_id in self.expected_node_ids)
        return {"type": "path_contains", "ok": ok, "expected": self.expected_node_ids, "seen": seen}


class AssertPathOrdered:
    def __init__(self, expected_node_ids: Iterable[str]) -> None:
        self.expected_node_ids = list(expected_node_ids)

    def check(self, *, event_log: list[dict[str, Any]]) -> dict[str, Any]:
        seen = [item.get("node_id") for item in event_log if item.get("event_type") == "node_entered"]
        cursor = 0
        for node_id in seen:
            if cursor < len(self.expected_node_ids) and node_id == self.expected_node_ids[cursor]:
                cursor += 1
        ok = cursor == len(self.expected_node_ids)
        return {"type": "path_ordered", "ok": ok, "expected": self.expected_node_ids, "seen": seen}


class AssertToolCalled:
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id

    def check(self, *, final_state: Any) -> dict[str, Any]:
        results = getattr(getattr(final_state, "tools", None), "tool_results", []) or []
        ok = any(item.get("output", {}).get("tool_id") == self.tool_id or item.get("tool_id") == self.tool_id for item in results)
        return {"type": "tool_called", "ok": ok, "tool_id": self.tool_id}


class AssertToolProposed:
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id

    def check(self, *, event_log: list[dict[str, Any]]) -> dict[str, Any]:
        ok = any(
            item.get("event_type") == "tool_proposed"
            and item.get("payload", {}).get("tool_id") == self.tool_id
            for item in event_log
        )
        return {"type": "tool_proposed", "ok": ok, "tool_id": self.tool_id}


class AssertToolApprovalRequired:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        policy = getattr(final_state, "policy", None)
        ok = bool(getattr(policy, "approval_required", False) or getattr(policy, "interrupt_required", False))
        return {"type": "tool_approval_required", "ok": ok}


class AssertPolicyBlocked:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        blocked = bool(getattr(getattr(final_state, "policy", None), "blocked", False))
        return {"type": "policy_blocked", "ok": blocked}


class AssertPolicyApprovalRequired:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        policy = getattr(final_state, "policy", None)
        ok = bool(getattr(policy, "approval_required", False) or getattr(policy, "interrupt_required", False))
        return {"type": "policy_approval_required", "ok": ok}


class AssertPolicyRefusal:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        policy = getattr(final_state, "policy", None)
        answer = getattr(getattr(final_state, "conversation", None), "final_answer", None)
        ok = bool(getattr(policy, "refusal_reason", None) or (getattr(policy, "blocked", False) and answer))
        return {"type": "policy_refusal", "ok": ok}


class AssertContextBuilt:
    def __init__(self, context_key: str) -> None:
        self.context_key = context_key

    def check(self, *, final_state: Any) -> dict[str, Any]:
        model_context = getattr(getattr(final_state, "context", None), "model_context", {}) or {}
        tool_context = getattr(getattr(final_state, "context", None), "tool_context", {}) or {}
        ok = self.context_key in model_context or self.context_key in tool_context
        return {"type": "context_built", "ok": ok, "context_key": self.context_key}


class AssertContextCompressed:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        compressed = bool(getattr(getattr(final_state, "context", None), "compression_applied", False))
        return {"type": "context_compressed", "ok": compressed}


class AssertHiddenContextKey:
    def __init__(self, context_key: str) -> None:
        self.context_key = context_key

    def check(self, *, final_state: Any) -> dict[str, Any]:
        hidden = getattr(getattr(final_state, "context", None), "hidden_context", {}) or {}
        return {"type": "hidden_context_key", "ok": self.context_key in hidden, "context_key": self.context_key}


class AssertCheckpointCreated:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        refs = getattr(getattr(final_state, "observability", None), "debug_refs", []) or []
        ok = any(item.get("kind") == "checkpoint" for item in refs)
        return {"type": "checkpoint_created", "ok": ok}


class AssertResumeEvent:
    def check(self, *, event_log: list[dict[str, Any]]) -> dict[str, Any]:
        ok = any(item.get("event_type") == "resume_completed" for item in event_log)
        return {"type": "resume_event", "ok": ok}


class AssertResumeContinuous:
    def check(self, *, event_log: list[dict[str, Any]]) -> dict[str, Any]:
        interrupted_at = None
        resumed_at = None
        for index, item in enumerate(event_log):
            if item.get("event_type") == "interrupt_triggered" and interrupted_at is None:
                interrupted_at = index
            if item.get("event_type") == "resume_started" and resumed_at is None:
                resumed_at = index
        ok = interrupted_at is not None and resumed_at is not None and interrupted_at < resumed_at
        return {"type": "resume_continuous", "ok": ok}


class AssertFinalAnswer:
    def __init__(self, expected: str) -> None:
        self.expected = expected

    def check(self, *, final_state: Any) -> dict[str, Any]:
        answer = getattr(getattr(final_state, "conversation", None), "final_answer", None)
        return {"type": "final_answer", "ok": answer == self.expected, "expected": self.expected, "actual": answer}


class AssertOutputContains:
    def __init__(self, expected: str) -> None:
        self.expected = expected

    def check(self, *, final_state: Any) -> dict[str, Any]:
        answer = getattr(getattr(final_state, "conversation", None), "final_answer", None) or ""
        return {
            "type": "output_contains",
            "ok": self.expected in answer,
            "expected": self.expected,
            "actual": answer,
        }
