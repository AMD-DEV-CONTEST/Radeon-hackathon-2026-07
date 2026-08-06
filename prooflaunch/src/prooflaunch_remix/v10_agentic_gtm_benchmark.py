from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


REQUIRED_KEYS = (
    "decision",
    "assumptions",
    "task_graph",
    "tool_calls",
    "artifacts",
    "risk_gates",
    "measurement_plan",
    "stop_conditions",
    "next_action",
)
REQUIRED_ARTIFACTS = (
    "launch_brief",
    "ad_concept",
    "email",
    "geo_answer_block",
)


@dataclass(frozen=True)
class AgenticGtmScore:
    json_valid: bool
    required_keys: int
    dependency_graph_valid: bool
    tool_calls_valid: bool
    artifact_coverage: int
    claim_provenance_gate: bool
    human_approval_gate: bool
    promotion_eligible: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "json_valid": self.json_valid,
            "required_keys": self.required_keys,
            "dependency_graph_valid": self.dependency_graph_valid,
            "tool_calls_valid": self.tool_calls_valid,
            "artifact_coverage": self.artifact_coverage,
            "claim_provenance_gate": self.claim_provenance_gate,
            "human_approval_gate": self.human_approval_gate,
            "promotion_eligible": self.promotion_eligible,
        }


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dependency_graph_valid(task_graph: Any) -> bool:
    if not isinstance(task_graph, list) or len(task_graph) < 6:
        return False
    seen: set[str] = set()
    for node in task_graph:
        if not isinstance(node, Mapping):
            return False
        node_id = node.get("id")
        dependencies = node.get("depends_on")
        if not isinstance(node_id, str) or not node_id or node_id in seen:
            return False
        if not isinstance(node.get("description"), str):
            return False
        if not isinstance(dependencies, list):
            return False
        if any(not isinstance(dep, str) or dep not in seen for dep in dependencies):
            return False
        seen.add(node_id)
    return True


def _tool_calls_valid(tool_calls: Any) -> bool:
    return (
        isinstance(tool_calls, list)
        and len(tool_calls) >= 1
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and bool(item["name"])
            and isinstance(item.get("arguments"), Mapping)
            for item in tool_calls
        )
    )


def score_agentic_gtm_output(content: str) -> AgenticGtmScore:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return AgenticGtmScore(False, 0, False, False, 0, False, False, False)
    if not isinstance(payload, Mapping):
        return AgenticGtmScore(False, 0, False, False, 0, False, False, False)

    required_count = sum(key in payload for key in REQUIRED_KEYS)
    artifacts = payload.get("artifacts")
    artifact_coverage = (
        sum(key in artifacts for key in REQUIRED_ARTIFACTS)
        if isinstance(artifacts, Mapping)
        else 0
    )
    risk_text = json.dumps(payload.get("risk_gates", ""), ensure_ascii=False).lower()
    provenance = any(token in risk_text for token in ("provenance", "evidence", "claim"))
    approval = any(token in risk_text for token in ("human", "approval", "approve"))
    graph_valid = _dependency_graph_valid(payload.get("task_graph"))
    tools_valid = _tool_calls_valid(payload.get("tool_calls"))
    eligible = all(
        (
            required_count == len(REQUIRED_KEYS),
            graph_valid,
            tools_valid,
            artifact_coverage == len(REQUIRED_ARTIFACTS),
            provenance,
            approval,
        )
    )
    return AgenticGtmScore(
        True,
        required_count,
        graph_valid,
        tools_valid,
        artifact_coverage,
        provenance,
        approval,
        eligible,
    )

