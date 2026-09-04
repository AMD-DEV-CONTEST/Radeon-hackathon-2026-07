"""End-to-end private multi-agent workflow for emergency screening."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol

from .contracts import run_transport_contract
from .knowledge import LocalKnowledgeBase
from .llm import ChatClient
from .memory import LocalMemoryStore
from .security import PermissionPolicy
from .site import SiteAgent


class WorkflowPlanner(Protocol):
    def plan(self, payload: Mapping[str, Any]) -> list[str]: ...


_REQUIRED_WORKFLOW = (
    "validate_permissions",
    "site_agent",
    "knowledge_retrieval",
    "environment_agent",
    "store_memory",
    "synthesize_report",
)


class DeterministicWorkflowPlanner:
    """Offline baseline exercising the complete allow-listed workflow."""

    def plan(self, payload: Mapping[str, Any]) -> list[str]:
        return list(_REQUIRED_WORKFLOW)


_WORKFLOW_SYSTEM_PROMPT = """You are the local-only planner for a nuclear emergency screening prototype.
Return ONLY a JSON list containing each required step exactly once and in this safe order:
validate_permissions, site_agent, knowledge_retrieval, environment_agent, store_memory, synthesize_report.
You may not calculate physical values, change inputs, access external networks, issue emergency advice,
or control equipment. Deterministic local tools produce every numerical result.
"""


class LocalWorkflowPlanner:
    """Strict adapter from a private chat client to the full workflow plan."""

    def __init__(self, client: ChatClient) -> None:
        self.client = client

    def plan(self, payload: Mapping[str, Any]) -> list[str]:
        messages = [
            {"role": "system", "content": _WORKFLOW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Plan this local screening case:\n"
                + json.dumps(dict(payload), sort_keys=True),
            },
        ]
        raw = self.client.chat(messages)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("workflow planner output must be a JSON list") from exc
        if not isinstance(parsed, list) or not all(
            isinstance(step, str) for step in parsed
        ):
            raise ValueError("workflow planner output must be a JSON list")
        return parsed


@dataclass(frozen=True)
class WorkflowRun:
    session_id: str
    plan: tuple[str, ...]
    site_assessment: dict[str, Any]
    knowledge_hits: tuple[dict[str, Any], ...]
    tool_result: dict[str, Any]
    memory_turns: int
    capabilities: dict[str, bool]
    denied_actions: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "plan": list(self.plan),
            "site_assessment": self.site_assessment,
            "knowledge_hits": [dict(hit) for hit in self.knowledge_hits],
            "tool_result": self.tool_result,
            "memory_turns": self.memory_turns,
            "capabilities": dict(self.capabilities),
            "denied_actions": list(self.denied_actions),
            "warnings": list(self.warnings),
        }


class EmergencyWorkflow:
    """Coordinates site, retrieval, physics, memory and permission agents."""

    _ALLOWED_STEPS = frozenset(_REQUIRED_WORKFLOW)

    def __init__(
        self,
        planner: WorkflowPlanner,
        knowledge_base: LocalKnowledgeBase,
        memory: LocalMemoryStore,
        policy: PermissionPolicy | None = None,
        site_agent: SiteAgent | None = None,
    ) -> None:
        self.planner = planner
        self.knowledge_base = knowledge_base
        self.memory = memory
        self.policy = policy or PermissionPolicy(role="analyst", local_only=True)
        self.site_agent = site_agent or SiteAgent()

    def run(self, case: Mapping[str, Any], session_id: str) -> WorkflowRun:
        if not isinstance(case.get("site"), Mapping):
            raise ValueError("workflow case requires a site object")
        if not isinstance(case.get("transport"), Mapping):
            raise ValueError("workflow case requires a transport object")
        query = case.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("workflow case requires a non-empty query")

        plan = tuple(self.planner.plan(case))
        unsupported = set(plan) - self._ALLOWED_STEPS
        if unsupported:
            raise ValueError(f"unsupported workflow step: {sorted(unsupported)[0]}")
        if plan != _REQUIRED_WORKFLOW:
            raise ValueError(
                "workflow plan must contain each required step exactly once in safe order"
            )

        self.policy.require("validate_input")
        self.policy.require("assess_site")
        site_assessment = self.site_agent.assess(case["site"]).to_dict()
        self.policy.require("retrieve_local_knowledge")
        hits = tuple(hit.to_dict() for hit in self.knowledge_base.search(query, limit=5))
        self.policy.require("simulate_transport")
        tool_result = run_transport_contract(case["transport"]).to_dict()

        self.memory.add_turn(
            session_id,
            role="user",
            content=query,
            metadata={
                "scenario_id": tool_result["scenario_id"],
                "site_id": site_assessment["site_id"],
                "operator_name": case.get("operator_name"),
            },
        )
        self.memory.add_turn(
            session_id,
            role="assistant",
            content=(
                f"Completed screening workflow for {tool_result['scenario_id']} with "
                f"{len(hits)} local knowledge citation(s)."
            ),
            metadata={"model_version": tool_result["model_version"]},
        )
        memory_turns = len(self.memory.recent(session_id, limit=1000))
        capabilities = {
            "local_knowledge_retrieval": bool(hits),
            "tool_invocation": tool_result["tool"] == "simulate_transport",
            "multi_step_planning": len(plan) > 1,
            "local_multi_turn_memory": memory_turns >= 2,
            "permission_privacy_control": self.policy.local_only,
        }
        warnings = tuple(
            dict.fromkeys(site_assessment["warnings"] + tool_result["warnings"])
        )
        return WorkflowRun(
            session_id=session_id,
            plan=plan,
            site_assessment=site_assessment,
            knowledge_hits=hits,
            tool_result=tool_result,
            memory_turns=memory_turns,
            capabilities=capabilities,
            denied_actions=self.policy.denied_actions,
            warnings=warnings,
        )
